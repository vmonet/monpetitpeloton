from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html


from .models import *

admin.site.register(Competition)
admin.site.register(Cyclist)
admin.site.register(League)
admin.site.register(Team)
admin.site.register(TeamCyclist)
admin.site.register(TeamCyclistAuction)
admin.site.register(LeagueAuction)
admin.site.register(LeagueRound)
admin.site.register(Role)
admin.site.register(BonusConfig)
admin.site.register(StageSelectionBonus)
admin.site.register(StageSelectionRider)
admin.site.register(CompetitionCyclistConfirmation)

@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ('name', 'competition', 'date')
    list_filter = ('competition',)
    search_fields = ('name',)

@admin.register(StageSelection)
class StageSelectionAdmin(admin.ModelAdmin):
    list_display = ('team', 'stage', 'submitted_at', 'validated')
    list_filter = ('stage', 'team', 'validated')
    search_fields = ('team__player__username', 'stage__name')