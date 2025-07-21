# NOTE: You need to create 'team_create.html' in your templates directory and add the necessary JS for the team selection UI.
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.views import View
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from .models import Cyclist, Team, League, TeamCyclistAuction, User, Competition, LeagueAuction, TeamCyclist, LeagueRound, Stage, StageSelection, StageSelectionBonus, BonusConfig, Role, StageSelectionRider, DefaultStageSelection, DefaultStageSelectionRider, StageGeneralResult, GeneralTimeResult, PointsGeneralResult, PointsTodayResult, KOMGeneralResult, KOMTodayResult, YouthGeneralResult, YouthTodayResult, TeamGeneralResult, TeamTodayResult
from django.views.decorators.csrf import csrf_exempt
import json
from django.contrib.auth.mixins import LoginRequiredMixin
import logging
from django import forms
from collections import defaultdict
from django.utils import timezone
from .forms import StageSelectionForm
from datetime import datetime, time as dt_time
from django.db.models import Count, Sum
from django.db.models import Prefetch

BUDGET = 500

@method_decorator(login_required, name='dispatch')
class TeamCreateView(View):
    """
    View for creating a fantasy team: displays cyclists, handles selection, and submission via AJAX/HTMX.
    """
    def get(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        team = Team.objects.filter(player=request.user, league=league).first()
        # Déterminer le round courant dynamiquement
        current_round = LeagueRound.objects.filter(league=league).order_by('-round_number').first().round_number
        # Récupérer la dernière soumission de ce joueur pour ce round
        league_auction = None
        if team:
            league_auction = LeagueAuction.get_latest_for_team_and_round(league, team, current_round)
        # Cyclistes déjà attribués à une équipe (TeamCyclist)
        team_cyclist_objs = TeamCyclist.objects.filter(league=league).select_related('cyclist', 'team', 'team__player')
        locked_cyclists = {}
        for tc in team_cyclist_objs:
            locked_cyclists[tc.cyclist.id] = {'locked': True, 'assigned_to': tc.team.player.username}
        # Tous les cyclistes (pour affichage à gauche)
        cyclists = Cyclist.objects.all()
        # Sélection du round en cours (TeamCyclistAuction du LeagueAuction courant)
        selected_cyclists = []
        if league_auction:
            teamcyclists = list(TeamCyclistAuction.objects.select_related('cyclist').filter(league_auction=league_auction))
            cyclist_map = {tc.cyclist.id: tc.cyclist for tc in teamcyclists}
            selected_cyclists = [
                {
                    'id': tc.cyclist.id,
                    'name': tc.cyclist.name,
                    'price': tc.price,
                    'value': tc.cyclist.value,
                    'team': tc.cyclist.team,
                    'status': tc.status,
                }
                for tc in teamcyclists
            ]
        # Cyclistes déjà dans la team (TeamCyclist pour ce team/league)
        team_cyclists = []
        teamcyclist_total = 0
        if team:
            team_cyclists_qs = list(TeamCyclist.objects.filter(team=team, league=league).select_related('cyclist'))
            team_cyclists = [
                {
                    'id': tc.cyclist.id,
                    'name': tc.cyclist.name,
                    'price': tc.price,
                    'value': tc.cyclist.value,
                    'team': tc.cyclist.team,
                }
                for tc in team_cyclists_qs
            ]
            teamcyclist_total = sum(tc.price for tc in team_cyclists_qs)
        remaining_budget = BUDGET - teamcyclist_total
        editing_allowed = league.is_active
        return render(request, 'team_create.html', {
            'cyclists': cyclists,
            'budget': BUDGET,
            'remaining_budget': remaining_budget,
            'league': league,
            'selected_cyclists': selected_cyclists or [],
            'locked_cyclists': locked_cyclists,
            'editing_allowed': editing_allowed,
            'team_cyclists': team_cyclists,
            'auction_finished': league.auction_finished,
        })

    @csrf_exempt
    def post(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        user = request.user
        team = Team.objects.filter(player=user, league=league).first()
        teamcyclist_total = 0
        team_cyclists_qs = []
        if team:
            team_cyclists_qs = list(TeamCyclist.objects.filter(team=team, league=league).select_related('cyclist'))
            teamcyclist_total = sum(tc.price for tc in team_cyclists_qs)
        remaining_budget = BUDGET - teamcyclist_total
        # Déterminer le round courant dynamiquement
        current_round = LeagueRound.objects.filter(league=league).order_by('-round_number').first().round_number
        try:
            data = json.loads(request.body)
            selected = data.get('cyclists', [])
        except Exception:
            return JsonResponse({'error': 'Invalid data.'}, status=400)
        # Nouvelle règle : joueurs déjà dans l'équipe + sélection >= 12
        total_cyclists = len(team_cyclists_qs)
        if total_cyclists + len(selected) < 12:
            return JsonResponse({'error': 'You must have at least 12 cyclists in total (current team + selection).'}, status=400)
        cyclist_ids = [c['id'] for c in selected]
        if len(set(cyclist_ids)) != len(cyclist_ids):
            return JsonResponse({'error': 'Duplicate cyclists.'}, status=400)
        cyclists = list(Cyclist.objects.filter(id__in=cyclist_ids))
        cyclist_map = {cy.id: cy for cy in cyclists}
        if len(cyclists) != len(selected):
            return JsonResponse({'error': 'Invalid cyclist(s).'}, status=400)
        total = 0
        for c in selected:
            cyclist = cyclist_map.get(c['id'])
            if not cyclist:
                return JsonResponse({'error': 'Cyclist not found.'}, status=400)
            price = float(c['price'])
            if price < cyclist.value:
                return JsonResponse({'error': f'Price for {cyclist.name} below minimum.'}, status=400)
            total += price
        if total != remaining_budget:
            return JsonResponse({'error': f'Total spent ({total}) does not match budget ({BUDGET}).'}, status=400)
        # Créer une nouvelle LeagueAuction pour ce team/league/round
        if not team:
            team = Team.objects.create(player=user, league=league)
        league_auction = LeagueAuction.objects.create(league=league, team=team, round_number=current_round)
        # Créer les TeamCyclistAuction associés
        cyclist_map = {cy.id: cy for cy in cyclists}
        tca_objs = [
            TeamCyclistAuction(
                league_auction=league_auction,
                cyclist=cyclist_map[c['id']],
                price=float(c['price']),
                status='pending'
            )
            for c in selected
        ]
        TeamCyclistAuction.objects.bulk_create(tca_objs)
        league_auction.check_and_resolve_auction()
        return JsonResponse({'success': True})

@method_decorator(login_required, name='dispatch')
class LeagueTeamStatusView(View):
    def get(self, request, league_id):
        league = get_object_or_404(League, id=league_id)
        # Check if user is a member
        if not Team.objects.filter(player=request.user, league=league).exists():
            return HttpResponseForbidden("You are not a member of this league.")
        # Déterminer le round courant dynamiquement
        current_round = LeagueRound.objects.filter(league=league).order_by('-round_number').first().round_number
        # Get all teams (members) and prefetch cyclists
        teams = Team.objects.filter(league=league).select_related('player').prefetch_related('team_cyclists')
        # Prefetch all TeamCyclists for these teams in this league
        teamcyclists = TeamCyclist.objects.filter(league=league)
        teamcyclists_by_team = {}
        for tc in teamcyclists:
            teamcyclists_by_team.setdefault(tc.team_id, []).append(tc)
        # Batch fetch latest auctions for all teams
        auctions = {team.id: LeagueAuction.get_latest_for_team_and_round(league, team, current_round) for team in teams}
        # Batch fetch all TeamCyclistAuctions for these auctions
        auction_ids = [a.id for a in auctions.values() if a]
        auction_cyclist_counts = {}
        if auction_ids:
            from django.db.models import Count as DJCount
            counts = TeamCyclistAuction.objects.filter(league_auction_id__in=auction_ids).values('league_auction_id').annotate(count=DJCount('id'))
            auction_cyclist_counts = {c['league_auction_id']: c['count'] for c in counts}
        status_list = []
        for team in teams:
            user = team.player
            league_auction = auctions.get(team.id)
            team_cyclists = teamcyclists_by_team.get(team.id, [])
            team_cyclist_count = len(team_cyclists)
            teamcyclist_total = sum(tc.price for tc in team_cyclists)
            remaining_budget = BUDGET - teamcyclist_total
            if league_auction:
                cyclist_count = auction_cyclist_counts.get(league_auction.id, 0)
                submitted = cyclist_count > 0
            else:
                cyclist_count = 0
                submitted = False
            finished = False
            if remaining_budget == 0 and team_cyclist_count >= 12:
                finished = True
            status_list.append({
                'username': user.username,
                'submitted': submitted,
                'finished': finished,
                'cyclist_count': cyclist_count,
                'team_cyclist_count': team_cyclist_count,
                'user_id': user.id,
                'remaining_budget': remaining_budget,
            })
        return render(request, 'league_team_status.html', {
            'league': league,
            'status_list': status_list,
            'current_user_id': request.user.id,
            'current_round':current_round,
            'auction_finished': league.auction_finished,
        })


class AdminTeamEditView(View):
    def dispatch(self, request, league_id, user_id, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponseForbidden("Only superusers can access this page.")
        self.target_user = get_object_or_404(User, id=user_id)
        self.league = get_object_or_404(League, id=league_id)
        return super().dispatch(request, league_id, user_id, *args, **kwargs)

    def get(self, request, league_id, user_id, *args, **kwargs):
        league = self.league
        team = Team.objects.filter(player=self.target_user, league=league).first()
        current_round = LeagueRound.objects.filter(league=league).order_by('-round_number').first().round_number
        league_auction = None
        if team:
            league_auction = LeagueAuction.get_latest_for_team_and_round(league, team, current_round)
        team_cyclist_objs = TeamCyclist.objects.filter(league=league)
        locked_cyclists = {}
        for tc in team_cyclist_objs.select_related('cyclist', 'team'):
            locked_cyclists[tc.cyclist.id] = {'locked': True, 'assigned_to': tc.team.player.username}
        cyclists = Cyclist.objects.all()
        selected_cyclists = []
        if league_auction:
            teamcyclists = TeamCyclistAuction.objects.select_related('cyclist').filter(league_auction=league_auction)
            selected_cyclists = [
                {
                    'id': tc.cyclist.id,
                    'name': tc.cyclist.name,
                    'price': tc.price,
                    'value': tc.cyclist.value,
                    'team': tc.cyclist.team,
                    'status': tc.status,
                }
                for tc in teamcyclists
            ]
        team_cyclists = []
        teamcyclist_total = 0
        if team:
            team_cyclists_qs = TeamCyclist.objects.filter(team=team, league=league).select_related('cyclist')
            team_cyclists = [
                {
                    'id': tc.cyclist.id,
                    'name': tc.cyclist.name,
                    'price': tc.price,
                    'value': tc.cyclist.value,
                    'team': tc.cyclist.team,
                }
                for tc in team_cyclists_qs
            ]
            teamcyclist_total = sum(tc.price for tc in team_cyclists_qs)
        remaining_budget = BUDGET - teamcyclist_total
        editing_allowed = True
        return render(request, 'team_create.html', {
            'cyclists': cyclists,
            'budget': BUDGET,
            'remaining_budget': remaining_budget,
            'league': league,
            'selected_cyclists': selected_cyclists or [],
            'admin_mode': True,
            'target_user': self.target_user,
            'locked_cyclists': locked_cyclists,
            'editing_allowed': editing_allowed,
            'team_cyclists': team_cyclists,
            'auction_finished': league.auction_finished,
        })

    @csrf_exempt
    def post(self, request, league_id, user_id, *args, **kwargs):
        league = self.league
        team = Team.objects.filter(player=self.target_user, league=league).first()
        teamcyclist_total = 0
        if team:
            team_cyclists_qs = TeamCyclist.objects.filter(team=team, league=league).select_related('cyclist')
            teamcyclist_total = sum(tc.price for tc in team_cyclists_qs)
        remaining_budget = BUDGET - teamcyclist_total
        current_round = LeagueRound.objects.filter(league=league).order_by('-round_number').first().round_number
        try:
            data = json.loads(request.body)
            selected = data.get('cyclists', [])
        except Exception:
            return JsonResponse({'error': 'Invalid data.'}, status=400)
        # Nouvelle règle : joueurs déjà dans l'équipe + sélection >= 12
        total_cyclists = teamcyclist_total and team_cyclists_qs.count() or 0
        if total_cyclists + len(selected) < 12:
            return JsonResponse({'error': 'You must have at least 12 cyclists in total (current team + selection).'}, status=400)
        cyclist_ids = [c['id'] for c in selected]
        if len(set(cyclist_ids)) != len(cyclist_ids):
            return JsonResponse({'error': 'Duplicate cyclists.'}, status=400)
        cyclists = Cyclist.objects.filter(id__in=cyclist_ids)
        if cyclists.count() != len(selected):
            return JsonResponse({'error': 'Invalid cyclist(s).'}, status=400)
        total = 0
        for c in selected:
            cyclist = next((cy for cy in cyclists if cy.id == c['id']), None)
            print(cyclist)
            if not cyclist:
                return JsonResponse({'error': 'Cyclist not found.'}, status=400)
            print("----------")
            price = float(c['price'])
            print(price)
            print(cyclist.value)
            print("----------")
            if price < cyclist.value:
                return JsonResponse({'error': f'Price for {cyclist.name} below minimum.'}, status=400)
            total += price
        if total != remaining_budget:
            return JsonResponse({'error': f'Total spent ({total}) does not match budget ({BUDGET}).'}, status=400)
        if not team:
            team = Team.objects.create(player=self.target_user, league=league)
        league_auction = LeagueAuction.objects.create(league=league, team=team, round_number=current_round)
        for c in selected:
            cyclist = next((cy for cy in cyclists if cy.id == c['id']), None)
            TeamCyclistAuction.objects.create(league_auction=league_auction, cyclist=cyclist, price=float(c['price']), status='pending')
        logger = logging.getLogger(__name__)
        logger.info(f"Admin {request.user} edited team for user {self.target_user} in league {league}")
        league_auction.check_and_resolve_auction()
        return JsonResponse({'success': True})

class LeagueTeamsListView(LoginRequiredMixin, View):
    def get(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        teams = Team.objects.filter(league=league).select_related('player')
        teams_data = []
        for team in teams:
            cyclists = TeamCyclist.objects.filter(team=team, league=league).select_related('cyclist')
            cyclists_data = [
                {
                    'name': tc.cyclist.name,
                    'team': tc.cyclist.team,
                    'price': tc.price,
                    'min_value': tc.cyclist.value,
                }
                for tc in cyclists
            ]
            teams_data.append({
                'player': team.player.username,
                'cyclists': cyclists_data,
            })
        return render(request, 'league_teams_list.html', {
            'league': league,
            'teams_data': teams_data,
            'auction_finished': league.auction_finished,
        })

class LeagueCreateForm(forms.ModelForm):
    class Meta:
        model = League
        fields = ['name', 'competition']

class LeagueCreateView(LoginRequiredMixin, View):
    def get(self, request):
        form = LeagueCreateForm()
        return render(request, 'league_create.html', {'form': form})

    def post(self, request):
        form = LeagueCreateForm(request.POST)
        if form.is_valid():
            league = form.save(commit=False)
            league.creator = request.user
            league.save()
            # Ajoute le créateur comme membre
            Team.objects.create(player=request.user, league=league)
            return redirect('league_team_status', league_id=league.id)
        return render(request, 'league_create.html', {'form': form})

class LeagueJoinForm(forms.Form):
    invite_code = forms.CharField(max_length=8, label="Invitation code")

class LeagueJoinView(LoginRequiredMixin, View):
    def get(self, request):
        form = LeagueJoinForm()
        return render(request, 'league_join.html', {'form': form})

    def post(self, request):
        form = LeagueJoinForm(request.POST)
        error = None
        if form.is_valid():
            code = form.cleaned_data['invite_code'].upper()
            try:
                league = League.objects.get(invite_code=code)
                # Ajoute le user si pas déjà membre (Team)
                Team.objects.get_or_create(player=request.user, league=league)
                return redirect('league_team_status', league_id=league.id)
            except League.DoesNotExist:
                error = "No league found with this code."
        return render(request, 'league_join.html', {'form': form, 'error': error})

class LeagueActivateView(LoginRequiredMixin, View):
    def post(self, request, league_id):
        league = get_object_or_404(League, id=league_id)
        if league.creator != request.user:
            return HttpResponseForbidden("Only the creator can activate this league.")
        league.is_active = True
        league.save()
        return redirect('league_team_status', league_id=league.id)

class HomepageView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        user_teams = Team.objects.filter(player=user).select_related('league__competition')
        leagues = list({team.league for team in user_teams})
        competitions = list({team.league.competition for team in user_teams})
        leagues.sort(key=lambda l: l.name)
        competitions.sort(key=lambda c: c.name)
        return render(request, 'homepage.html', {
            'competitions': competitions,
            'leagues': leagues,
        })

class LeagueAuctionResultsView(LoginRequiredMixin, View):
    def get(self, request, league_id):
        league = get_object_or_404(League, id=league_id)
        if not Team.objects.filter(player=request.user, league=league).exists():
            return HttpResponseForbidden("You are not a member of this league.")
        # Récupérer toutes les enchères de la ligue, tous rounds confondus
        all_bids = TeamCyclistAuction.objects.filter(
            league_auction__league=league
        ).select_related('cyclist', 'league_auction__team__player', 'league_auction')
        # On prépare une liste à plat avec round, joueur, coureur, prix, statut
        flat_bids = [
            {
                'round': bid.league_auction.round_number,
                'player': bid.league_auction.team.player.username,
                'cyclist': bid.cyclist,
                'cyclist_id': bid.cyclist.id,
                'price': bid.price,
                'status': bid.status,
            }
            for bid in all_bids
            if bid.status in ('won', 'lost', 'Won', 'Lost')
        ]
        # Pour chaque cycliste, trouver le prix d'achat max (enchère gagnante)
        max_price_by_cyclist = defaultdict(float)
        for b in flat_bids:
            if b['status'] == 'won':
                max_price_by_cyclist[b['cyclist_id']] = max(max_price_by_cyclist[b['cyclist_id']], b['price'])
        # Ordonner : cycliste avec le prix d'achat max le plus élevé en premier, puis pour chaque cycliste, enchères décroissantes
        # en cas d'égalité d'enchères, le gagnant en premier
        flat_bids.sort(key=lambda b: (-max_price_by_cyclist.get(b['cyclist_id'], 0), b['cyclist'].name.lower(), -b['price'], -1 if b['status'] == 'won' else 1))
        return render(request, 'auction_results.html', {
            'league': league,
            'flat_bids': flat_bids,
            'auction_finished': league.auction_finished,
        })

class CompetitionStagesView(LoginRequiredMixin, View):
    """
    Displays a list of all stages for a given competition, with links to the selection page for each.
    """
    def get(self, request, competition_id, *args, **kwargs):
        competition = get_object_or_404(Competition, id=competition_id)
        stages = Stage.objects.filter(competition=competition).order_by('date')
        return render(request, 'competition_stages.html', {
            'competition': competition,
            'stages': stages
        })

class StageSelectionView(LoginRequiredMixin, View):
    """
    View for players to select up to 8 riders for a given stage. Selection is locked after 12:00 PM on the stage date.
    Only riders from the validated team can be selected.
    """
    def get(self, request, stage_id, *args, **kwargs):
        stage = get_object_or_404(Stage, id=stage_id)
        team = Team.objects.filter(player=request.user, league__competition=stage.competition).first()
        if not team:
            return HttpResponseForbidden("You do not have a team for this competition.")
        # Lock selection after 12:00 PM on stage date
        now = timezone.localtime()
        lock_time = timezone.make_aware(datetime.combine(stage.date, dt_time(12, 0)))
        locked = now >= lock_time
        selection = StageSelection.objects.filter(team=team, stage=stage).first()
        form = StageSelectionForm(instance=selection, team=team)
        return render(request, 'stage_selection.html', {
            'stage': stage,
            'form': form,
            'locked': locked,
            'selection': selection,
        })

    def post(self, request, stage_id, *args, **kwargs):
        stage = get_object_or_404(Stage, id=stage_id)
        team = Team.objects.filter(player=request.user, league__competition=stage.competition).first()
        if not team:
            return HttpResponseForbidden("You do not have a team for this competition.")
        now = timezone.localtime()
        lock_time = timezone.make_aware(datetime.combine(stage.date, dt_time(12, 0)))
        if now >= lock_time:
            return HttpResponseForbidden("Selection is locked for this stage (after 12:00 PM).")
        selection, created = StageSelection.objects.get_or_create(team=team, stage=stage)
        form = StageSelectionForm(request.POST, instance=selection, team=team)
        if form.is_valid():
            form.save()
            return redirect('stage_selection', stage_id=stage.id)
        return render(request, 'stage_selection.html', {
            'stage': stage,
            'form': form,
            'locked': False,
            'selection': selection,
        })

def get_current_stage(competition):
    """
    Returns the current stage of the competition.
    If there's a stage today, returns that stage.
    If not, returns the next upcoming stage.
    If no upcoming stages, returns the last stage.
    """
    today = timezone.localtime().date()
    
    # Try to get today's stage
    stage = Stage.objects.filter(
        competition=competition,
        date=today
    ).first()
    
    if not stage:
        # Try to get the next stage
        stage = Stage.objects.filter(
            competition=competition,
            date__gt=today
        ).order_by('date').first()
        
        if not stage:
            # If no upcoming stage, get the last stage
            stage = Stage.objects.filter(
                competition=competition,
                date__lt=today
            ).order_by('-date').first()
    
    return stage

class StageSelectionLeagueView(LoginRequiredMixin, View):
    """
    Page for selecting the team for a stage in a league. Shows a stage selector, available riders (left), and current selection (right).
    """
    def get(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        stages = Stage.objects.filter(competition=league.competition).order_by('date')
        stage_id = request.GET.get('stage')
        
        if stage_id:
            stage = get_object_or_404(Stage, id=stage_id)
        else:
            stage = get_current_stage(league.competition) or stages.first()
            
        team = Team.objects.filter(player=request.user, league=league).first()
        if not team:
            return HttpResponseForbidden("You are not a member of this league.")

        roles = list(Role.objects.all().order_by('order'))
        unique_role_ids = list(Role.objects.filter(name__in=['leader', 'sprinteur', 'grimpeur']).order_by('order').values_list('id', flat=True))
        
        # --- Default selection logic with optimized queries ---
        default_selection = DefaultStageSelection.objects.prefetch_related(
            Prefetch('riders', queryset=DefaultStageSelectionRider.objects.select_related('cyclist', 'role'))
        ).filter(team=team).order_by('-created_at').first()
        default_riders = []
        default_roles = {}
        if default_selection:
            rider_role_order = {}
            for sr in default_selection.riders.all():
                default_roles[sr.cyclist.id] = sr.role.id if sr.role else ''
                rider_role_order[sr.cyclist.id] = sr.role.order if sr.role else 999
            default_riders = sorted(
                [sr.cyclist for sr in default_selection.riders.all()],
                key=lambda rider: rider_role_order.get(rider.id, 999)
            )
        # --- End default selection logic ---
        # --- Stage selection logic with optimized queries ---
        selection = None
        initial_riders = []
        initial_roles = {}
        stage_selection_qs = StageSelection.objects.prefetch_related(
            Prefetch('selection_riders', queryset=StageSelectionRider.objects.select_related('cyclist', 'role'))
        ).filter(team=team, stage=stage).order_by('-validated', '-submitted_at')
        selection = next(iter(stage_selection_qs), None)
        if selection:
            rider_role_order = {}
            for sr in selection.selection_riders.all():
                initial_roles[sr.cyclist.id] = sr.role.id if sr.role else ''
                rider_role_order[sr.cyclist.id] = sr.role.order if sr.role else 999
            initial_riders = sorted(
                [sr.cyclist for sr in selection.selection_riders.all()],
                key=lambda rider: rider_role_order.get(rider.id, 999)
            )
        form_initial = {'riders': initial_riders}
        form = StageSelectionForm(initial=form_initial, team=team, stage=stage, competition=league.competition)
        locked = False
        if stage:
            now = timezone.localtime()
            lock_time = timezone.make_aware(datetime.combine(stage.date, dt_time(12, 0)))
            locked = now >= lock_time
        # --- Bonuses and validated selections optimized ---
        bonuses = list(BonusConfig.objects.filter(competition=league.competition))
        used_bonuses = {bonus.id: [] for bonus in bonuses}
        available_bonuses = {bonus.id: bonus.max_per_player for bonus in bonuses}
        selections_validated = StageSelection.objects.filter(team=team, validated=True).prefetch_related(
            Prefetch('stageselectionbonus_set', queryset=StageSelectionBonus.objects.select_related('bonus', 'stage_selection__stage'))
        )
        for sel in selections_validated:
            for sb in sel.stageselectionbonus_set.all():
                used_bonuses[sb.bonus.id].append(sel.stage)
                available_bonuses[sb.bonus.id] -= sb.count
        for bonus in bonuses:
            if available_bonuses[bonus.id] < 0:
                available_bonuses[bonus.id] = 0
        selected_bonuses_for_stage = []
        if selection:
            selected_bonuses_for_stage = list(selection.stageselectionbonus_set.select_related('bonus').all())
        any_bonus_used = any(used_bonuses[bonus.id] for bonus in bonuses)
        selected_bonus_ids_for_stage = [sb.bonus.id for sb in selected_bonuses_for_stage]
        display_riders = initial_riders[:8] + [None] * (8 - len(initial_riders))
        # Pass default selection to template
        return render(request, 'stage_selection_league.html', {
            'league': league,
            'stages': stages,
            'stage': stage,
            'form': form,
            'locked': locked,
            'bonuses': bonuses,
            'used_bonuses': used_bonuses,
            'available_bonuses': available_bonuses,
            'roles': roles,
            'initial_roles': initial_roles,
            'initial_riders': initial_riders,
            'display_riders': display_riders,
            'unique_role_ids': unique_role_ids,
            'selected_bonuses_for_stage': selected_bonuses_for_stage,
            'any_bonus_used': any_bonus_used,
            'selected_bonus_ids_for_stage': selected_bonus_ids_for_stage,
            'default_riders': default_riders,
            'default_roles': default_roles,
            'auction_finished': league.auction_finished,
        })

    def post(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        team = Team.objects.filter(player=request.user, league=league).first()
        if not team:
            return HttpResponseForbidden("You are not a member of this league.")
        stages = list(Stage.objects.filter(competition=league.competition).order_by('date'))
        stage_id = request.POST.get('stage')
        stage = get_object_or_404(Stage, id=stage_id) if stage_id else stages[0]
        roles = list(Role.objects.all().order_by('order'))
        unique_role_ids = list(Role.objects.filter(name__in=['leader', 'sprinteur', 'grimpeur']).order_by('order').values_list('id', flat=True))
        now = timezone.localtime()
        lock_time = timezone.make_aware(datetime.combine(stage.date, dt_time(12, 0)))
        if now >= lock_time:
            return HttpResponseForbidden("Selection is locked for this stage (after 12:00 PM).")
        action = request.POST.get('action')
        from .models import DefaultStageSelection, DefaultStageSelectionRider
        if action == 'set_default':
            # Save a default selection using the new model
            rider_ids = request.POST.getlist('riders')
            role_map = {}
            for rider_id in rider_ids:
                role_id = request.POST.get(f'role_{rider_id}', '')
                if role_id:
                    role_map[int(rider_id)] = int(role_id)
            if len(rider_ids) == 8 and len(role_map) == len(roles):
                DefaultStageSelection.objects.filter(team=team).delete()
                selection = DefaultStageSelection.objects.create(team=team)
                for rider_id in rider_ids:
                    role_id = role_map.get(int(rider_id))
                    DefaultStageSelectionRider.objects.create(
                        default_selection=selection,
                        cyclist_id=int(rider_id),
                        role_id=role_id
                    )
                return redirect(f"{request.path}?stage={stage.id}")
        elif action == 'apply_default':
            # Apply default selection to this stage
            default_selection = DefaultStageSelection.objects.filter(team=team).order_by('-created_at').first()
            if default_selection:
                StageSelection.objects.filter(team=team, stage=stage).delete()
                selection = StageSelection.objects.create(
                    team=team,
                    stage=stage,
                    validated=True,
                )
                for sr in default_selection.riders.select_related('cyclist', 'role').all():
                    StageSelectionRider.objects.create(
                        stage_selection=selection,
                        cyclist=sr.cyclist,
                        role=sr.role
                    )
                return redirect(f"{request.path}?stage={stage.id}")
        elif action == 'apply_default_all':
            # Apply default selection to all stages not yet set up
            default_selection = DefaultStageSelection.objects.filter(team=team).order_by('-created_at').first()
            if default_selection:
                for s in stages:
                    exists = StageSelection.objects.filter(team=team, stage=s, validated=True).exists()
                    if not exists:
                        selection = StageSelection.objects.create(
                            team=team,
                            stage=s,
                            validated=True,
                        )
                        for sr in default_selection.riders.select_related('cyclist', 'role').all():
                            StageSelectionRider.objects.create(
                                stage_selection=selection,
                                cyclist=sr.cyclist,
                                role=sr.role
                            )
                return redirect(f"{request.path}?stage={stage.id}")
        elif action is None or action == '' or action == 'validate' or action is None:
            # Normal selection logic (restored)
            rider_ids = request.POST.getlist('riders')
            role_map = {}
            for rider_id in rider_ids:
                role_id = request.POST.get(f'role_{rider_id}', '')
                if role_id:
                    role_map[int(rider_id)] = int(role_id)
            errors = []
            if len(rider_ids) != 8:
                errors.append("You must select exactly 8 riders.")
            if not role_map:
                errors.append("You must assign at least one role to a rider.")
            role_ids_required = set(role.id for role in roles)
            role_ids_selected = set(role_map.values())
            if role_ids_selected != role_ids_required:
                errors.append("You must assign each role exactly once in your selection.")
            form = StageSelectionForm(request.POST, team=team, stage=stage, competition=league.competition)
            if form.is_valid() and not errors:
                StageSelection.objects.filter(team=team, stage=stage).update(validated=False)
                selection = StageSelection.objects.create(
                    team=team,
                    stage=stage,
                    validated=True,
                )
                for rider_id in rider_ids:
                    role_id = role_map.get(int(rider_id))
                    StageSelectionRider.objects.create(
                        stage_selection=selection,
                        cyclist_id=int(rider_id),
                        role_id=role_id
                    )
                selected_bonuses_str = request.POST.get('selected_bonuses', '')
                selected_bonus_ids = [int(bid) for bid in selected_bonuses_str.split(',') if bid.strip()]
                if len(selected_bonus_ids) > 1:
                    selected_bonus_ids = selected_bonus_ids[:1]
                StageSelectionBonus.objects.filter(stage_selection=selection).delete()
                for bonus_id in selected_bonus_ids:
                    StageSelectionBonus.objects.create(stage_selection=selection, bonus_id=bonus_id, count=1)
                return redirect(f"{request.path}?stage={stage.id}")
            # If errors, fall through to fallback render
        # Fallback: always return a response
        # Rebuild context as in get
        # --- Default selection logic with optimized queries ---
        default_selection = DefaultStageSelection.objects.prefetch_related(
            Prefetch('riders', queryset=DefaultStageSelectionRider.objects.select_related('cyclist', 'role'))
        ).filter(team=team).order_by('-created_at').first()
        default_riders = []
        default_roles = {}
        if default_selection:
            rider_role_order = {}
            for sr in default_selection.riders.all():
                default_roles[sr.cyclist.id] = sr.role.id if sr.role else ''
                rider_role_order[sr.cyclist.id] = sr.role.order if sr.role else 999
            default_riders = sorted(
                [sr.cyclist for sr in default_selection.riders.all()],
                key=lambda rider: rider_role_order.get(rider.id, 999)
            )
        # --- Stage selection logic with optimized queries ---
        selection = None
        initial_riders = []
        initial_roles = {}
        stage_selection_qs = StageSelection.objects.prefetch_related(
            Prefetch('selection_riders', queryset=StageSelectionRider.objects.select_related('cyclist', 'role'))
        ).filter(team=team, stage=stage).order_by('-validated', '-submitted_at')
        selection = next(iter(stage_selection_qs), None)
        if selection:
            rider_role_order = {}
            for sr in selection.selection_riders.all():
                initial_roles[sr.cyclist.id] = sr.role.id if sr.role else ''
                rider_role_order[sr.cyclist.id] = sr.role.order if sr.role else 999
            initial_riders = sorted(
                [sr.cyclist for sr in selection.selection_riders.all()],
                key=lambda rider: rider_role_order.get(rider.id, 999)
            )
        form_initial = {'riders': initial_riders}
        form = StageSelectionForm(initial=form_initial, team=team, stage=stage, competition=league.competition)
        locked = False
        if stage:
            now = timezone.localtime()
            lock_time = timezone.make_aware(datetime.combine(stage.date, dt_time(12, 0)))
            locked = now >= lock_time
        # --- Bonuses and validated selections optimized ---
        bonuses = list(BonusConfig.objects.filter(competition=league.competition))
        used_bonuses = {bonus.id: [] for bonus in bonuses}
        available_bonuses = {bonus.id: bonus.max_per_player for bonus in bonuses}
        selections_validated = StageSelection.objects.filter(team=team, validated=True).prefetch_related(
            Prefetch('stageselectionbonus_set', queryset=StageSelectionBonus.objects.select_related('bonus', 'stage_selection__stage'))
        )
        for sel in selections_validated:
            for sb in sel.stageselectionbonus_set.all():
                used_bonuses[sb.bonus.id].append(sel.stage)
                available_bonuses[sb.bonus.id] -= sb.count
        for bonus in bonuses:
            if available_bonuses[bonus.id] < 0:
                available_bonuses[bonus.id] = 0
        selected_bonuses_for_stage = []
        if selection:
            selected_bonuses_for_stage = list(selection.stageselectionbonus_set.select_related('bonus').all())
        any_bonus_used = any(used_bonuses[bonus.id] for bonus in bonuses)
        selected_bonus_ids_for_stage = [sb.bonus.id for sb in selected_bonuses_for_stage]
        display_riders = initial_riders[:8] + [None] * (8 - len(initial_riders))
        return render(request, 'stage_selection_league.html', {
            'league': league,
            'stages': stages,
            'stage': stage,
            'form': form,
            'locked': locked,
            'bonuses': bonuses,
            'used_bonuses': used_bonuses,
            'available_bonuses': available_bonuses,
            'roles': roles,
            'initial_roles': initial_roles,
            'initial_riders': initial_riders,
            'display_riders': display_riders,
            'unique_role_ids': unique_role_ids,
            'selected_bonuses_for_stage': selected_bonuses_for_stage,
            'any_bonus_used': any_bonus_used,
            'selected_bonus_ids_for_stage': selected_bonus_ids_for_stage,
            'default_riders': default_riders,
            'default_roles': default_roles,
            'auction_finished': league.auction_finished,
        })

class PelotonView(LoginRequiredMixin, View):
    def get(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        stages = Stage.objects.filter(competition=league.competition).order_by('date')
        stage_id = request.GET.get('stage')
        
        if stage_id:
            stage = get_object_or_404(Stage, id=stage_id)
        else:
            stage = get_current_stage(league.competition) or stages.first()
            
        teams = Team.objects.filter(league=league)

        # Check if we're past noon on race day
        now = timezone.localtime()
        lock_time = timezone.make_aware(datetime.combine(stage.date, dt_time(12, 0)))
        locked = now >= lock_time

        selections = {}
        for team in teams:
            selection = StageSelection.objects.filter(
                team=team,
                stage=stage,
                validated=True
            ).prefetch_related(
                'selection_riders__cyclist',
                'selection_riders__role',
                'stageselectionbonus_set__bonus'
            ).first()
            if selection:
                # Sort riders by role order
                riders = list(selection.selection_riders.all())
                riders_sorted = sorted(
                    riders,
                    key=lambda rider: rider.role.order if rider.role else 999
                )
                selections[team.id] = {
                    'riders': riders_sorted,
                    'bonuses': list(selection.stageselectionbonus_set.all())
                }

        return render(request, 'peloton_view.html', {
            'league': league,
            'stages': stages,
            'stage': stage,
            'teams': teams,
            'selections': selections,
            'locked': locked,
        })

@method_decorator(login_required, name='dispatch')
class LeagueResultsView(View):
    """
    Vue pour afficher les résultats d'une compétition avec sélecteur d'étape et onglets.
    """
    def get(self, request, league_id):
        league = get_object_or_404(League, id=league_id)
        
        # Vérifier que l'utilisateur est membre de la ligue
        if not Team.objects.filter(player=request.user, league=league).exists():
            return HttpResponseForbidden("Vous n'êtes pas membre de cette ligue.")
        
        competition = league.competition
        stages = Stage.objects.filter(competition=competition).order_by('date')
        
        # Récupérer l'étape sélectionnée (par défaut la première)
        selected_stage_id = request.GET.get('stage')
        if selected_stage_id:
            selected_stage = get_object_or_404(Stage, id=selected_stage_id, competition=competition)
        else:
            selected_stage = stages.first()
        
        # Récupérer les résultats pour l'étape sélectionnée
        results = {}
        if selected_stage:
            results = {
                'stage_general': StageGeneralResult.objects.filter(stage=selected_stage).order_by('rnk'),
                'general_time': GeneralTimeResult.objects.filter(stage=selected_stage).order_by('rnk'),
                'points_general': PointsGeneralResult.objects.filter(stage=selected_stage).order_by('rnk'),
                'points_today': PointsTodayResult.objects.filter(stage=selected_stage).order_by('rnk'),
                'kom_general': KOMGeneralResult.objects.filter(stage=selected_stage).order_by('rnk'),
                'kom_today': KOMTodayResult.objects.filter(stage=selected_stage).order_by('rnk'),
                'youth_general': YouthGeneralResult.objects.filter(stage=selected_stage).order_by('rnk'),
                'youth_today': YouthTodayResult.objects.filter(stage=selected_stage).order_by('rnk'),
                'team_general': TeamGeneralResult.objects.filter(stage=selected_stage).order_by('rnk'),
                'team_today': TeamTodayResult.objects.filter(stage=selected_stage).order_by('rnk'),
            }
        
        # Définir les labels des onglets
        tab_labels = {
            'stage_general': 'Classement Général',
            'general_time': 'Classement Temps',
            'points_general': 'Points - Général',
            'points_today': 'Points - Aujourd\'hui',
            'kom_general': 'KOM - Général',
            'kom_today': 'KOM - Aujourd\'hui',
            'youth_general': 'Jeunes - Général',
            'youth_today': 'Jeunes - Aujourd\'hui',
            'team_general': 'Équipes - Général',
            'team_today': 'Équipes - Aujourd\'hui'
        }
        
        return render(request, 'league_results.html', {
            'league': league,
            'competition': competition,
            'stages': stages,
            'selected_stage': selected_stage,
            'results': results,
            'tab_labels': tab_labels,
        })