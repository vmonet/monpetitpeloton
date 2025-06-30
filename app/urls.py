from django.urls import path

from . import views
from .views import TeamCreateView, LeagueTeamStatusView, AdminTeamEditView, LeagueTeamsListView, LeagueCreateView, LeagueJoinView, LeagueActivateView, HomepageView, StageSelectionView, CompetitionStagesView, StageSelectionLeagueView, PelotonView

urlpatterns = [
    path("", HomepageView.as_view(), name="homepage"),
    path("league/<int:league_id>/team/create/", TeamCreateView.as_view(), name="team_create"),
    path("league/<int:league_id>/team/status/", LeagueTeamStatusView.as_view(), name="league_team_status"),
    path("adminview/league/<int:league_id>/team/<int:user_id>/", AdminTeamEditView.as_view(), name="admin_team_edit"),
    path("league/<int:league_id>/teams/", LeagueTeamsListView.as_view(), name="league_teams_list"),
    path("league/create/", LeagueCreateView.as_view(), name="league_create"),
    path("league/join/", LeagueJoinView.as_view(), name="league_join"),
    path("league/<int:league_id>/activate/", LeagueActivateView.as_view(), name="league_activate"),
    path("league/<int:league_id>/auction/results/", views.LeagueAuctionResultsView.as_view(), name="auction_results"),
    path("competition/<int:competition_id>/stages/", CompetitionStagesView.as_view(), name="competition_stages"),
    path("stage/<int:stage_id>/select/", StageSelectionView.as_view(), name="stage_selection"),
    path("league/<int:league_id>/stage-selection/", StageSelectionLeagueView.as_view(), name="stage_selection_league"),
    path("league/<int:league_id>/peloton/", PelotonView.as_view(), name="peloton_view"),
]