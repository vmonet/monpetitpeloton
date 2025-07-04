# NOTE: After editing models, run: python manage.py makemigrations && python manage.py migrate
from django.db import models
from django.contrib.auth import get_user_model
from django.db import transaction
from collections import defaultdict
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
import random
import string
import uuid

User = get_user_model()

class Competition(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Cyclist(models.Model):
    name = models.CharField(max_length=255)
    team = models.CharField(max_length=255)
    value = models.IntegerField()  # Minimum price (int)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.team})"

class League(models.Model):
    name = models.CharField(max_length=255)
    creator = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="leagues_created"
    )
    competition = models.ForeignKey(
        Competition,
        on_delete=models.CASCADE,
        related_name="leagues"
    )
    invite_code = models.CharField(max_length=8, unique=True, blank=True, null=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    auction_finished = models.BooleanField(default=None, null=True, blank=True, help_text="True si les enchères sont terminées, NULL sinon.")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.invite_code:
            self.invite_code = self.generate_invite_code()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_invite_code(length=8):
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=length))
            if not League.objects.filter(invite_code=code).exists():
                return code

# Création automatique du premier round à la création d'une league
@receiver(post_save, sender=League)
def create_first_round(sender, instance, created, **kwargs):
    if created:
        from .models import LeagueRound  # avoid circular import
        if not LeagueRound.objects.filter(league=instance, round_number=1).exists():
            LeagueRound.objects.create(
                competition=instance.competition,
                league=instance,
                round_number=1,
                is_active=True
            )

class TeamCyclist(models.Model):
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='team_cyclists')
    league = models.ForeignKey('League', on_delete=models.CASCADE, related_name='league_cyclists', default=None)
    cyclist = models.ForeignKey('Cyclist', on_delete=models.CASCADE, related_name='team_cyclists')
    price = models.IntegerField()
    locked = models.BooleanField(default=False)  # True if assigned definitively
    submitted_at = models.DateTimeField(auto_now_add=True)  # When the bid was submitted
    
    class Meta:
        unique_together = ('league', 'cyclist')

    def __str__(self):
        return f"{self.cyclist.name} in {self.team} for {self.price}"

class LeagueAuction(models.Model):
    league = models.ForeignKey('League', on_delete=models.CASCADE, related_name='auctions')
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='auctions')
    round_number = models.PositiveIntegerField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Auction for {self.team} in {self.league} (Round {self.round_number})"

    @staticmethod
    def get_latest_for_team_and_round(league, team, round_number):
        return LeagueAuction.objects.filter(league=league, team=team, round_number=round_number).order_by('-submitted_at').first()

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        # if is_new:
        #     self.check_and_resolve_auction()

    def check_and_resolve_auction(self):
        teams = Team.objects.filter(league=self.league)
        all_ready = True
        for team in teams:
            print(f"[DEBUG] Checking team: {team}")
            latest_auction = LeagueAuction.get_latest_for_team_and_round(self.league, team, self.round_number)
            team_cyclist_count = TeamCyclist.objects.filter(team=team, league=self.league).count()
            teamcyclist_total = sum(tc.price for tc in TeamCyclist.objects.filter(team=team, league=self.league))
            remaining_budget = 500 - teamcyclist_total
            if not latest_auction:
                if team_cyclist_count >= 12 or remaining_budget == 0:
                    continue  # Team is complete, skip auction check
                all_ready = False
                print(f"[WARN] No auction found for team {team}")
                break
            cyclist_count = TeamCyclistAuction.objects.filter(league_auction=latest_auction).count()
            print(f"[DEBUG] Cyclists submitted for team {team}: {cyclist_count}")
            if cyclist_count + team_cyclist_count < 12 and remaining_budget > 0:
                all_ready = False
                break
        if all_ready:
            print("[INFO] All teams ready, resolving auction")
            resolve_auctions_for_league(self.league.id, self.round_number)


class TeamCyclistAuction(models.Model):
    league_auction = models.ForeignKey('LeagueAuction', on_delete=models.CASCADE, related_name='bids')
    cyclist = models.ForeignKey('Cyclist', on_delete=models.CASCADE, related_name='team_cyclists_auction')
    price = models.FloatField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=255, choices=[('pending', 'Pending'), ('won', 'Won'), ('lost', 'Lost')])

    class Meta:
        unique_together = ('league_auction', 'cyclist')

    def __str__(self):
        return f"{self.cyclist.name} in {self.league_auction.id} for {self.price} ({self.status})"


class Team(models.Model):
    player = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="teams"
    )
    league = models.ForeignKey(
        League,
        on_delete=models.CASCADE,
        related_name="teams"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Team of {self.player} in {self.league}"

    @property
    def is_complete(self):
        won_cyclists = self.team_cyclists_auction.filter(status='won').count()
        total_won_price = sum(tc.price for tc in self.team_cyclists_auction.filter(status='won'))
        return won_cyclists >= 12 and total_won_price == 100  # or use BUDGET if variable

def resolve_auctions_for_league(league_id, round_number):
    league = League.objects.get(id=league_id)
    teams = Team.objects.filter(league=league)
    # On ne prend que les dernières LeagueAuction de chaque team pour ce round
    latest_auctions = {
        team.id: LeagueAuction.get_latest_for_team_and_round(league, team, round_number)
        for team in teams
    }
    # Récupère tous les TeamCyclistAuction "pending" pour ces LeagueAuction
    all_bids = TeamCyclistAuction.objects.filter(
        league_auction__in=[a for a in latest_auctions.values() if a],
        status='pending'
    )
    cyclist_bids = defaultdict(list)
    for bid in all_bids.select_related('cyclist', 'league_auction__team'):
        cyclist_bids[bid.cyclist_id].append(bid)
    assignments = {}
    with transaction.atomic():
        for cyclist_id, bids in cyclist_bids.items():
            if len(bids) == 1:
                bid = bids[0]
                bid.status = 'won'
                bid.save()
                assignments[cyclist_id] = bid.league_auction.team_id
            else:
                bids.sort(key=lambda b: (-b.price, b.submitted_at))
                winner = bids[0]
                winner.status = 'won'
                winner.save()
                assignments[cyclist_id] = winner.league_auction.team_id
                for loser in bids[1:]:
                    loser.status = 'lost'
                    loser.save()
        # After assignment, check team completeness (pour ce round)
        all_complete = True
        for team in teams:
            auction = latest_auctions.get(team.id)
            if not auction:
                continue
            won_bids = TeamCyclistAuction.objects.filter(league_auction=auction, status='won')
            for tc in won_bids:
                # Crée un TeamCyclist si non existant pour ce team, league, cyclist
                TeamCyclist.objects.get_or_create(
                    team=team,
                    league=league,
                    cyclist=tc.cyclist,
                    defaults={
                        'price': tc.price,
                        'locked': True
                    }
                )
            won_count = won_bids.count()
            total_won_price = sum(tc.price for tc in won_bids)
            team_complete = won_count >= 12 and total_won_price == 500
            # Optionnel : stocker le statut de complétude
            if not team_complete:
                all_complete = False
        # Si toutes les équipes sont complètes, close le round et crée le suivant
        if not all_complete:
            current_round = LeagueRound.objects.get(league=league, round_number=round_number)
            current_round.close_and_create_next()
        # Si toutes les équipes sont complètes pour la ligue, on marque auction_finished à True
        league_complete = all(
            TeamCyclist.objects.filter(team=team, league=league).count() >= 12 and
            sum(tc.price for tc in TeamCyclist.objects.filter(team=team, league=league)) == 500
            for team in teams
        )
        if league_complete:
            league.auction_finished = True
            league.save()
    return assignments

class LeagueRound(models.Model):
    competition = models.ForeignKey('Competition', on_delete=models.CASCADE, related_name='rounds')
    league = models.ForeignKey('League', on_delete=models.CASCADE, related_name='rounds')
    round_number = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('league', 'round_number')

    def __str__(self):
        return f"Round {self.round_number} for {self.league.name} (active={self.is_active})"

    @staticmethod
    def get_active(league):
        return LeagueRound.objects.filter(league=league, is_active=True).order_by('-round_number').first()

    def close_and_create_next(self):
        self.is_active = False
        self.ended_at = timezone.now()
        self.save()
        next_round = LeagueRound.objects.create(
            competition=self.competition,
            league=self.league,
            round_number=self.round_number + 1,
            is_active=True
        )
        return next_round

class Stage(models.Model):
    """
    Represents a stage in a cycling competition (e.g., a stage of the Tour de France).
    Linked to a Competition, with a name, date, and a constant max_riders (8).
    """
    name = models.CharField(max_length=255)
    date = models.DateField()
    competition = models.ForeignKey('Competition', on_delete=models.CASCADE, related_name='stages')

    MAX_RIDERS = 8  # Maximum number of riders a player can select for this stage

    def __str__(self):
        return f"{self.name} ({self.competition.name})"

class BonusConfig(models.Model):
    """
    Configures a bonus for a competition. Admin can set how many times each bonus can be used per player.
    """
    competition = models.ForeignKey('Competition', on_delete=models.CASCADE, related_name='bonus_configs')
    name = models.CharField(max_length=100)
    max_per_player = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.name} ({self.competition.name})"

class Role(models.Model):
    """
    Defines a possible role for a cyclist in a stage selection (e.g., leader, sprinteur, grimpeur, coéquipier).
    """
    name = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.label

class StageSelection(models.Model):
    """
    Stores a selection of riders for a given team (player) and stage.
    Multiple selections can exist per team/stage (history kept).
    The 'validated' field marks the last valid selection before the lock (12:00 PM on stage day).
    Riders and their roles are now managed via StageSelectionRider.
    """
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='stage_selections')
    stage = models.ForeignKey('Stage', on_delete=models.CASCADE, related_name='selections')
    submitted_at = models.DateTimeField(auto_now_add=True)
    validated = models.BooleanField(default=False, help_text="Is this the last valid selection before lock?")
    bonuses = models.ManyToManyField('BonusConfig', through='StageSelectionBonus', related_name='stage_selections', blank=True)
    # Plus de champ riders, leader, sprinteur, grimpeur ici

    def __str__(self):
        return f"Selection for {self.team} on {self.stage} (validated={self.validated})"

class StageSelectionRider(models.Model):
    """
    Associates a cyclist and a role to a StageSelection (i.e., a rider's role for a given stage selection).
    """
    stage_selection = models.ForeignKey(StageSelection, on_delete=models.CASCADE, related_name='selection_riders')
    cyclist = models.ForeignKey('Cyclist', on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = ('stage_selection', 'cyclist')

    def __str__(self):
        return f"{self.cyclist} as {self.role} in {self.stage_selection}"

class StageSelectionBonus(models.Model):
    """
    Through model for StageSelection <-> BonusConfig, to store how many times a bonus is used on a stage selection.
    """
    stage_selection = models.ForeignKey(StageSelection, on_delete=models.CASCADE)
    bonus = models.ForeignKey(BonusConfig, on_delete=models.CASCADE)
    count = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('stage_selection', 'bonus')

    def __str__(self):
        return f"{self.stage_selection} - {self.bonus} x{self.count}"

class CompetitionCyclistConfirmation(models.Model):
    competition = models.ForeignKey('Competition', on_delete=models.CASCADE, related_name='cyclist_confirmations')
    cyclist = models.ForeignKey('Cyclist', on_delete=models.CASCADE, related_name='competition_confirmations')
    is_confirmed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('competition', 'cyclist')

    def __str__(self):
        return f"{self.cyclist} confirmé: {self.is_confirmed} pour {self.competition}"

class DefaultStageSelection(models.Model):
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='default_stage_selections')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Default selection for {self.team}" 

class DefaultStageSelectionRider(models.Model):
    default_selection = models.ForeignKey(DefaultStageSelection, on_delete=models.CASCADE, related_name='riders')
    cyclist = models.ForeignKey('Cyclist', on_delete=models.CASCADE)
    role = models.ForeignKey('Role', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = ('default_selection', 'cyclist')

    def __str__(self):
        return f"{self.cyclist} as {self.role} in {self.default_selection}"

class Resultat(models.Model):
    stage = models.ForeignKey('Stage', on_delete=models.CASCADE, related_name='resultats')
    insert_batch_id = models.UUIDField(default=uuid.uuid4, editable=False)
    rnk = models.CharField(max_length=10, blank=True, null=True)
    gc = models.CharField(max_length=10, blank=True, null=True)
    timelag = models.CharField(max_length=20, blank=True, null=True)
    bib = models.CharField(max_length=10, blank=True, null=True)
    h2h = models.CharField(max_length=10, blank=True, null=True)
    specialty = models.CharField(max_length=50, blank=True, null=True)
    rider = models.CharField(max_length=255, blank=True, null=True)
    age = models.CharField(max_length=10, blank=True, null=True)
    team = models.CharField(max_length=255, blank=True, null=True)
    uci = models.CharField(max_length=20, blank=True, null=True)
    pnt = models.CharField(max_length=10, blank=True, null=True)
    time = models.CharField(max_length=20, blank=True, null=True)
    insert_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.rider} ({self.team}) - {self.insert_batch_id}"
