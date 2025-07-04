from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django import forms
from django.shortcuts import redirect
from django.urls import path
from django.contrib import messages
import csv
from io import TextIOWrapper
from django.http import JsonResponse
from bs4 import BeautifulSoup

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

class CSVImportForm(forms.Form):
    competition = forms.ModelChoiceField(queryset=None, required=True, label="Compétition")
    stage = forms.ModelChoiceField(queryset=Stage.objects.none(), required=True, label="Étape")
    csv_file = forms.FileField(label="Fichier CSV")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['competition'].queryset = Competition.objects.all()
        if 'competition' in self.data:
            try:
                competition_id = int(self.data.get('competition'))
                self.fields['stage'].queryset = Stage.objects.filter(competition_id=competition_id)
            except (ValueError, TypeError):
                self.fields['stage'].queryset = Stage.objects.none()
        elif self.initial.get('competition'):
            competition = self.initial.get('competition')
            self.fields['stage'].queryset = Stage.objects.filter(competition=competition)

class HTMLImportForm(forms.Form):
    competition = forms.ModelChoiceField(queryset=None, required=True, label="Compétition")
    stage = forms.ModelChoiceField(queryset=Stage.objects.none(), required=True, label="Étape")
    html_file = forms.FileField(label="Fichier HTML")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['competition'].queryset = Competition.objects.all()
        if 'competition' in self.data:
            try:
                competition_id = int(self.data.get('competition'))
                self.fields['stage'].queryset = Stage.objects.filter(competition_id=competition_id)
            except (ValueError, TypeError):
                self.fields['stage'].queryset = Stage.objects.none()
        elif self.initial.get('competition'):
            competition = self.initial.get('competition')
            self.fields['stage'].queryset = Stage.objects.filter(competition=competition)

@admin.register(Resultat)
class ResultatAdmin(admin.ModelAdmin):
    list_display = ("rnk", "gc", "timelag", "bib", "h2h", "specialty", "rider", "age", "team", "uci", "pnt", "time", "insert_date", "insert_batch_id", "stage")
    list_filter = ("stage", "team")
    search_fields = ("rider", "team", "bib")
    change_list_template = "admin/resultat_changelist.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('import-csv/', self.admin_site.admin_view(self.import_csv), name='resultat_import_csv'),
            path('import-html/', self.admin_site.admin_view(self.import_html), name='resultat_import_html'),
            path('get-stages/', self.admin_site.admin_view(self.get_stages), name='get_stages'),
        ]
        return custom_urls + urls

    def import_csv(self, request):
        from .models import Stage, Resultat
        import uuid
        if request.method == "POST":
            form = CSVImportForm(request.POST, request.FILES)
            if form.is_valid():
                competition = form.cleaned_data['competition']
                stage = form.cleaned_data['stage']
                csv_file = request.FILES['csv_file']
                insert_batch_id = uuid.uuid4()
                reader = csv.DictReader(TextIOWrapper(csv_file.file, encoding='utf-8'))
                count = 0
                for row in reader:
                    Resultat.objects.create(
                        stage=stage,
                        insert_batch_id=insert_batch_id,
                        rnk=row.get('Rnk'),
                        gc=row.get('GC'),
                        timelag=row.get('Timelag'),
                        bib=row.get('BIB'),
                        h2h=row.get('H2H'),
                        specialty=row.get('Specialty'),
                        rider=row.get('Rider'),
                        age=row.get('Age'),
                        team=row.get('Team'),
                        uci=row.get('UCI'),
                        pnt=row.get('Pnt'),
                        time=row.get('Time'),
                    )
                    count += 1
                self.message_user(request, f"{count} résultats importés (batch {insert_batch_id}).", messages.SUCCESS)
                return redirect("..")
        else:
            form = CSVImportForm()
        all_stages = list(Stage.objects.all().values('id', 'name', 'competition_id'))
        context = dict(
            self.admin_site.each_context(request),
            form=form,
            all_stages=all_stages,
            import_type='csv',
        )
        from django.shortcuts import render
        return render(request, "admin/import_csv.html", context)

    def import_html(self, request):
        from .models import Stage, Resultat
        import uuid
        if request.method == "POST":
            form = HTMLImportForm(request.POST, request.FILES)
            if form.is_valid():
                competition = form.cleaned_data['competition']
                stage = form.cleaned_data['stage']
                html_file = request.FILES['html_file']
                insert_batch_id = uuid.uuid4()
                # --- Parsing HTML ici (BeautifulSoup ou autre) ---
                from bs4 import BeautifulSoup
                import tempfile
                import os
                with tempfile.NamedTemporaryFile(delete=False, suffix='.html') as tmp_html:
                    tmp_html.write(html_file.read())
                    tmp_html_path = tmp_html.name
                with open(tmp_html_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, "html.parser")
                    table = soup.find("table")
                    rows = []
                    for tr in table.find_all("tr")[1:]:
                        rows.append([td.get_text(strip=True) for td in tr.find_all("td")])
                # À adapter selon l'ordre des colonnes dans le HTML !
                count = 0
                for row in rows:
                    Resultat.objects.create(
                        stage=stage,
                        insert_batch_id=insert_batch_id,
                        rnk=row[0] if len(row) > 0 else None,
                        gc=row[1] if len(row) > 1 else None,
                        timelag=row[2] if len(row) > 2 else None,
                        bib=row[3] if len(row) > 3 else None,
                        h2h=row[4] if len(row) > 4 else None,
                        specialty=row[5] if len(row) > 5 else None,
                        rider=row[6] if len(row) > 6 else None,
                        age=row[7] if len(row) > 7 else None,
                        team=row[8] if len(row) > 8 else None,
                        uci=row[9] if len(row) > 9 else None,
                        pnt=row[10] if len(row) > 10 else None,
                        time=row[11] if len(row) > 11 else None,
                    )
                    count += 1
                os.remove(tmp_html_path)
                self.message_user(request, f"{count} résultats importés depuis HTML (batch {insert_batch_id}).", messages.SUCCESS)
                return redirect("..")
        else:
            form = HTMLImportForm()
        all_stages = list(Stage.objects.all().values('id', 'name', 'competition_id'))
        context = dict(
            self.admin_site.each_context(request),
            form=form,
            all_stages=all_stages,
            import_type='html',
        )
        from django.shortcuts import render
        return render(request, "admin/import_csv.html", context)

    def get_stages(self, request):
        competition_id = request.GET.get('competition_id')
        stages = []
        if competition_id:
            stages = Stage.objects.filter(competition_id=competition_id).values('id', 'name')
        return JsonResponse({'stages': list(stages)})