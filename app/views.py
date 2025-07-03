# NOTE: You need to create 'team_create.html' in your templates directory and add the necessary JS for the team selection UI.
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.views import View
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from .models import Cyclist, Team, League, TeamCyclistAuction, User, Competition, LeagueAuction, TeamCyclist, LeagueRound, Stage, StageSelection, StageSelectionBonus, BonusConfig, Role, StageSelectionRider
from django.views.decorators.csrf import csrf_exempt
import json
from django.contrib.auth.mixins import LoginRequiredMixin
import logging
from django import forms
from collections import defaultdict
from django.utils import timezone
from .forms import StageSelectionForm
from datetime import datetime, time as dt_time

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
        team_cyclist_objs = TeamCyclist.objects.filter(league=league)
        locked_cyclists = {}
        for tc in team_cyclist_objs.select_related('cyclist', 'team'):
            locked_cyclists[tc.cyclist.id] = {'locked': True, 'assigned_to': tc.team.player.username}
        # Tous les cyclistes (pour affichage à gauche)
        cyclists = Cyclist.objects.all()
        # Sélection du round en cours (TeamCyclistAuction du LeagueAuction courant)
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
        # Cyclistes déjà dans la team (TeamCyclist pour ce team/league)
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
        editing_allowed = league.is_active
        # if league_auction and any(tc['status'] == 'won' for tc in selected_cyclists):
        #     editing_allowed = False
        return render(request, 'team_create.html', {
            'cyclists': cyclists,
            'budget': BUDGET,
            'remaining_budget': remaining_budget,
            'league': league,
            'selected_cyclists': selected_cyclists or [],
            'locked_cyclists': locked_cyclists,
            'editing_allowed': editing_allowed,
            'team_cyclists': team_cyclists,
        })

    @csrf_exempt
    def post(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        user = request.user
        team = Team.objects.filter(player=user, league=league).first()
        teamcyclist_total = 0
        if team:
            team_cyclists_qs = TeamCyclist.objects.filter(team=team, league=league).select_related('cyclist')
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
        for c in selected:
            cyclist = next((cy for cy in cyclists if cy.id == c['id']), None)
            TeamCyclistAuction.objects.create(league_auction=league_auction, cyclist=cyclist, price=float(c['price']), status='pending')
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
        # Get all teams (members)
        teams = Team.objects.filter(league=league).select_related('player')
        status_list = []
        for team in teams:
            user = team.player
            league_auction = LeagueAuction.get_latest_for_team_and_round(league, team, current_round)
            team_cyclist_count = TeamCyclist.objects.filter(team=team).count()
            remaining_budget = BUDGET
            if team_cyclist_count > 0:
                team_cyclists_qs = TeamCyclist.objects.filter(team=team, league=league)
                teamcyclist_total = sum(tc.price for tc in team_cyclists_qs)
                remaining_budget = BUDGET - teamcyclist_total
            if league_auction:
                cyclist_count = TeamCyclistAuction.objects.filter(league_auction=league_auction).count()
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
            'current_round':current_round
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

class StageSelectionLeagueView(LoginRequiredMixin, View):
    """
    Page for selecting the team for a stage in a league. Shows a stage selector, available riders (left), and current selection (right).
    """
    def get(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        team = Team.objects.filter(player=request.user, league=league).first()
        if not team:
            return HttpResponseForbidden("You are not a member of this league.")
        stages = Stage.objects.filter(competition=league.competition).order_by('date')
        stage_id = request.GET.get('stage')
        stage = get_object_or_404(Stage, id=stage_id) if stage_id else stages.first()
        roles = list(Role.objects.all().order_by('order'))
        unique_role_ids = list(Role.objects.filter(name__in=['Leader', 'Sprinteur', 'Grimpeur']).order_by('order').values_list('id', flat=True))
        # Préremplir la sélection et les rôles
        selection = None
        initial_riders = []
        initial_roles = {}
        if stage:
            selection = StageSelection.objects.filter(team=team, stage=stage, validated=True).order_by('-submitted_at').first()
            if not selection:
                selection = StageSelection.objects.filter(team=team, stage=stage).order_by('-submitted_at').first()
            if selection:
                # Associer chaque rider à l'ordre de son rôle
                rider_role_order = {}
                for sr in selection.selection_riders.all():
                    initial_roles[sr.cyclist.id] = sr.role.id if sr.role else ''
                    rider_role_order[sr.cyclist.id] = sr.role.order if sr.role else 999
                # Trier les riders selon l'ordre du rôle
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
        # Prépare la liste des bonus utilisés et disponibles pour ce joueur dans la ligue
        bonuses = list(BonusConfig.objects.filter(competition=league.competition))
        used_bonuses = {bonus.id: [] for bonus in bonuses}
        available_bonuses = {bonus.id: bonus.max_per_player for bonus in bonuses}
        selections_validated = StageSelection.objects.filter(team=team, validated=True)
        for sel in selections_validated:
            for sb in sel.stageselectionbonus_set.all():
                used_bonuses[sb.bonus.id].append(sel.stage)
                available_bonuses[sb.bonus.id] -= sb.count
        for bonus in bonuses:
            if available_bonuses[bonus.id] < 0:
                available_bonuses[bonus.id] = 0
        selected_bonuses_for_stage = []
        if stage and team:
            selection = StageSelection.objects.filter(team=team, stage=stage, validated=True).order_by('-submitted_at').first()
            if not selection:
                selection = StageSelection.objects.filter(team=team, stage=stage).order_by('-submitted_at').first()
            if selection:
                selected_bonuses_for_stage = list(selection.stageselectionbonus_set.all())
        any_bonus_used = any(used_bonuses[bonus.id] for bonus in bonuses)
        selected_bonus_ids_for_stage = [sb.bonus.id for sb in selected_bonuses_for_stage]
        # Après le tri de initial_riders
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
        })

    def post(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        team = Team.objects.filter(player=request.user, league=league).first()
        if not team:
            return HttpResponseForbidden("You are not a member of this league.")
        stages = Stage.objects.filter(competition=league.competition).order_by('date')
        stage_id = request.POST.get('stage')
        stage = get_object_or_404(Stage, id=stage_id) if stage_id else stages.first()
        roles = list(Role.objects.all().order_by('order'))
        unique_role_ids = list(Role.objects.filter(name__in=['leader', 'sprinteur', 'grimpeur']).order_by('order').values_list('id', flat=True))
        now = timezone.localtime()
        lock_time = timezone.make_aware(datetime.combine(stage.date, dt_time(12, 0)))
        if now >= lock_time:
            return HttpResponseForbidden("Selection is locked for this stage (after 12:00 PM).")
        form = StageSelectionForm(request.POST, team=team, stage=stage, competition=league.competition)
        # Récupère les rôles depuis le POST
        rider_ids = request.POST.getlist('riders')
        role_map = {}
        for rider_id in rider_ids:
            role_id = request.POST.get(f'role_{rider_id}', '')
            if role_id:
                role_map[int(rider_id)] = int(role_id)
        errors = []
        if len(rider_ids) != 8:
            errors.append("You must select exactly 8 riders.")
        # Nouvelle règle : au moins un coureur avec un rôle
        if not role_map:
            errors.append("You must assign at least one role to a rider.")
        # Nouvelle règle : chaque rôle doit être attribué exactement une fois
        role_ids_required = set(role.id for role in roles)
        role_ids_selected = set(role_map.values())
        if role_ids_selected != role_ids_required:
            errors.append("You must assign each role exactly once in your selection.")
        if form.is_valid() and not errors:
            StageSelection.objects.filter(team=team, stage=stage).update(validated=False)
            selection = StageSelection.objects.create(
                team=team,
                stage=stage,
                validated=True,
            )
            # Crée les StageSelectionRider
            for rider_id in rider_ids:
                role_id = role_map.get(int(rider_id))
                StageSelectionRider.objects.create(
                    stage_selection=selection,
                    cyclist_id=int(rider_id),
                    role_id=role_id
                )
            # Gère les bonus sélectionnés via les tags
            selected_bonuses_str = request.POST.get('selected_bonuses', '')
            selected_bonus_ids = [int(bid) for bid in selected_bonuses_str.split(',') if bid.strip()]
            # Limite à un seul bonus sélectionné
            if len(selected_bonus_ids) > 1:
                selected_bonus_ids = selected_bonus_ids[:1]
            # Supprime les bonus existants pour cette sélection (sécurité)
            StageSelectionBonus.objects.filter(stage_selection=selection).delete()
            for bonus_id in selected_bonus_ids:
                StageSelectionBonus.objects.create(stage_selection=selection, bonus_id=bonus_id, count=1)
            return redirect(f"{request.path}?stage={stage.id}")
        locked = False
        now = timezone.localtime()
        lock_time = timezone.make_aware(datetime.combine(stage.date, dt_time(12, 0)))
        locked = now >= lock_time
        bonus_field_names = [field_name for field_name, _ in getattr(form, 'bonus_fields', [])]
        for err in errors:
            form.add_error(None, err)
        # Pour réafficher la sélection et les rôles sélectionnés
        initial_roles = {}
        for rider_id in rider_ids:
            role_id = request.POST.get(f'role_{rider_id}', '')
            if role_id:
                initial_roles[int(rider_id)] = int(role_id)
        # initial_riders pour affichage à droite
        if len(rider_ids) == 8:
            initial_riders = list(form.fields['riders'].queryset.filter(id__in=rider_ids))
        else:
            initial_riders = []
        # Après le tri de initial_riders
        display_riders = initial_riders[:8] + [None] * (8 - len(initial_riders))
        initial_riders = []
        initial_roles = {}
        if stage:
            selection = StageSelection.objects.filter(team=team, stage=stage, validated=True).order_by('-submitted_at').first()
            if not selection:
                selection = StageSelection.objects.filter(team=team, stage=stage).order_by('-submitted_at').first()
            if selection:
                # Associer chaque rider à l'ordre de son rôle
                rider_role_order = {}
                for sr in selection.selection_riders.all():
                    initial_roles[sr.cyclist.id] = sr.role.id if sr.role else ''
                    rider_role_order[sr.cyclist.id] = sr.role.order if sr.role else 999
                # Trier les riders selon l'ordre du rôle
                initial_riders = sorted(
                    [sr.cyclist for sr in selection.selection_riders.all()],
                    key=lambda rider: rider_role_order.get(rider.id, 999)
                )
        form.initial['riders'] = list(form.fields['riders'].queryset.filter(id__in=rider_ids))
        bonuses = list(BonusConfig.objects.filter(competition=league.competition))
        used_bonuses = {bonus.id: [] for bonus in bonuses}
        available_bonuses = {bonus.id: bonus.max_per_player for bonus in bonuses}
        selections_validated = StageSelection.objects.filter(team=team, validated=True)
        for sel in selections_validated:
            for sb in sel.stageselectionbonus_set.all():
                used_bonuses[sb.bonus.id].append(sel.stage)
                available_bonuses[sb.bonus.id] -= sb.count
        for bonus in bonuses:
            if available_bonuses[bonus.id] < 0:
                available_bonuses[bonus.id] = 0
        selected_bonuses_for_stage = []
        if stage and team:
            selection = StageSelection.objects.filter(team=team, stage=stage, validated=True).order_by('-submitted_at').first()
            if not selection:
                selection = StageSelection.objects.filter(team=team, stage=stage).order_by('-submitted_at').first()
            if selection:
                selected_bonuses_for_stage = list(selection.stageselectionbonus_set.all())
        any_bonus_used = any(used_bonuses[bonus.id] for bonus in bonuses)
        selected_bonus_ids_for_stage = [sb.bonus.id for sb in selected_bonuses_for_stage]
        return render(request, 'stage_selection_league.html', {
            'league': league,
            'stages': stages,
            'stage': stage,
            'form': form,
            'locked': locked,
            'bonus_field_names': bonus_field_names,
            'roles': roles,
            'initial_roles': initial_roles,
            'unique_role_ids': unique_role_ids,
            'initial_riders': initial_riders,
            'display_riders': display_riders,
            'bonuses': bonuses,
            'used_bonuses': used_bonuses,
            'available_bonuses': available_bonuses,
            'selected_bonuses_for_stage': selected_bonuses_for_stage,
            'any_bonus_used': any_bonus_used,
            'selected_bonus_ids_for_stage': selected_bonus_ids_for_stage,
        })

class PelotonView(LoginRequiredMixin, View):
    """
    View to display all teams' selections for a given stage in a league. Stage selector + table of selections.
    """
    def get(self, request, league_id, *args, **kwargs):
        league = get_object_or_404(League, id=league_id)
        stages = Stage.objects.filter(competition=league.competition).order_by('date')
        stage_id = request.GET.get('stage')
        stage = get_object_or_404(Stage, id=stage_id) if stage_id else stages.first()
        teams = Team.objects.filter(league=league).select_related('player')
        # Retourne la liste des cyclistes sélectionnés et leur rôle pour chaque team à cette étape
        selections = {}
        for team in teams:
            selection = StageSelection.objects.filter(team=team, stage=stage, validated=True).order_by('-submitted_at').first()
            if not selection:
                selection = StageSelection.objects.filter(team=team, stage=stage).order_by('-submitted_at').first()
            if selection:
                selections[team.id] = [
                    {'cyclist': sr.cyclist, 'role': sr.role} for sr in selection.selection_riders.all()
                ]
            else:
                selections[team.id] = []
        return render(request, 'peloton_view.html', {
            'league': league,
            'stages': stages,
            'stage': stage,
            'teams': teams,
            'selections': selections,
        })