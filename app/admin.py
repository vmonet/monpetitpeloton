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
        from .models import Stage, Resultat, GeneralResult, PointsResult, FinishPointsResult, KOMResult, GeneralTimeResult, YouthResult
        import uuid
        if request.method == "POST":
            form = HTMLImportForm(request.POST, request.FILES)
            if form.is_valid():
                competition = form.cleaned_data['competition']
                stage = form.cleaned_data['stage']
                html_file = request.FILES['html_file']
                insert_batch_id = uuid.uuid4()
                
                # Lit le contenu HTML
                html_content = html_file.read().decode('utf-8')
                
                # Utilise la nouvelle fonction de parsing
                counts = parse_html_results(html_content, stage, insert_batch_id)
                
                # Affiche un message de succès avec les détails
                total_count = sum(counts.values())
                message_parts = [f"{total_count} résultats importés (batch {insert_batch_id})"]
                for result_type, count in counts.items():
                    if count > 0:
                        message_parts.append(f"{count} {result_type}")
                
                self.message_user(request, " - ".join(message_parts), messages.SUCCESS)
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

def parse_html_results(html_content, stage, insert_batch_id):
    """
    Parse le contenu HTML et insère les résultats dans les modèles Django appropriés.
    Détecte automatiquement le type de chaque table et l'insère dans le bon modèle.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Compteurs pour chaque type de résultat
    counts = {
        'stage_general': 0,
        'general_time': 0,
        'points_general': 0,
        'points_today': 0,
        'kom_general': 0,
        'kom_today': 0,
        'youth_general': 0,
        'youth_today': 0,
        'team_general': 0,
        'team_today': 0
    }
    
    # Trouve toutes les resTab
    res_tabs = soup.find_all('div', class_='resTab')
    
    for res_tab in res_tabs:
        data_id = res_tab.get('data-id')
        
        # Détermine le type de classement selon data-id
        if data_id == '282552':
            # Stage General
            general_div = res_tab.find('div', class_='general')
            if general_div:
                table = general_div.find('table')
                if table:
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['stage_general'] = insert_stage_general_results(rows, headers, stage, insert_batch_id)
        
        elif data_id == '303507':
            # General Time
            general_div = res_tab.find('div', class_='general')
            if general_div:
                table = general_div.find('table')
                if table:
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['general_time'] = insert_general_time_results(rows, headers, stage, insert_batch_id)
        
        elif data_id == '303508':
            # Points (General + Today)
            general_div = res_tab.find('div', class_='general')
            if general_div:
                table = general_div.find('table')
                if table:
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['points_general'] = insert_points_general_results(rows, headers, stage, insert_batch_id)
            
            today_div = res_tab.find('div', class_='today')
            if today_div:
                table = today_div.find('table')
                if table:
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['points_today'] = insert_points_today_results(rows, headers, stage, insert_batch_id)
        
        elif data_id == '303510':
            # KOM/Sprints (General + Today)
            general_div = res_tab.find('div', class_='general')
            if general_div:
                table = general_div.find('table')
                if table:
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['kom_general'] = insert_kom_general_results(rows, headers, stage, insert_batch_id)
            
            today_div = res_tab.find('div', class_='today')
            if today_div:
                # KOM Today peut avoir plusieurs sous-tables
                tables = today_div.find_all('table')
                for table in tables:
                    h4_before = table.find_previous_sibling('h4')
                    kom_type = h4_before.get_text() if h4_before else "KOM Sprint"
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['kom_today'] += insert_kom_today_results(rows, headers, stage, insert_batch_id, kom_type)
        
        elif data_id == '303509':
            # Youth (General + Today)
            general_div = res_tab.find('div', class_='general')
            if general_div:
                table = general_div.find('table')
                if table:
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['youth_general'] = insert_youth_general_results(rows, headers, stage, insert_batch_id)
            
            today_div = res_tab.find('div', class_='today')
            if today_div:
                table = today_div.find('table')
                if table:
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['youth_today'] = insert_youth_today_results(rows, headers, stage, insert_batch_id)
        
        elif data_id == '303511':
            # Team (General + Today)
            general_div = res_tab.find('div', class_='general')
            if general_div:
                table = general_div.find('table')
                if table:
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['team_general'] = insert_team_general_results(rows, headers, stage, insert_batch_id)
            
            today_div = res_tab.find('div', class_='today')
            if today_div:
                table = today_div.find('table')
                if table:
                    rows = table.find('tbody').find_all('tr')
                    headers = [th.get('data-code') for th in table.find('thead').find_all('th')]
                    counts['team_today'] = insert_team_today_results(rows, headers, stage, insert_batch_id)
    
    return counts

def determine_table_type(title, index):
    """
    Détermine le type de table selon le titre ou l'ordre d'apparition.
    """
    title_lower = title.lower()
    
    if 'points at finish' in title_lower or 'bonis' in title_lower:
        return 'finish_points'
    elif 'kom' in title_lower or 'sprint' in title_lower or 'col' in title_lower or 'côte' in title_lower:
        return 'kom'
    elif 'youth' in title_lower or 'jeunes' in title_lower:
        return 'youth'
    elif 'points' in title_lower and 'general' not in title_lower:
        return 'points'
    elif 'time' in title_lower and 'general' in title_lower:
        return 'general_time'
    else:
        # Par défaut selon l'ordre d'apparition
        if index == 0:
            return 'general'
        elif index == 1:
            return 'points'
        elif index == 2:
            return 'finish_points'
        elif index == 3:
            return 'kom'
        elif index == 4:
            return 'general_time'
        elif index == 5:
            return 'youth'
        else:
            return 'general'

def safe_int(value):
    """Convertit une valeur en entier de manière sécurisée."""
    if not value or value == '' or value == ',,':
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

def safe_bool(value):
    """Convertit une valeur en booléen de manière sécurisée."""
    if not value or value == '' or value == ',,':
        return None
    return bool(value)

def extract_rider_name(cell):
    """Extrait le nom du coureur depuis une cellule HTML."""
    if not cell:
        return None
    
    # Si c'est déjà une chaîne, on la retourne
    if isinstance(cell, str):
        return cell.strip()
    
    # Si c'est un objet BeautifulSoup, on extrait le texte du lien
    if hasattr(cell, 'find'):
        link = cell.find('a')
        if link:
            return link.get_text(strip=True)
        return cell.get_text(strip=True)
    
    return str(cell).strip()

def insert_stage_general_results(rows, headers, stage, insert_batch_id):
    """Insère les résultats du classement général de l'étape"""
    from .models import StageGeneralResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            StageGeneralResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                gc=data.get('gc'),
                timelag=data.get('gc_timelag'),
                bib=safe_int(data.get('bib')),
                h2h=safe_bool(data.get('h2h')),
                specialty=extract_specialty(cells[5] if len(cells) > 5 else None),
                age=safe_int(data.get('age')),
                rider=extract_rider_name(cells[7] if len(cells) > 7 else None),
                team=extract_team_name(cells[8] if len(cells) > 8 else None),
                uci=data.get('uci_pnt'),
                pnt=data.get('pnt'),
                bonis=data.get('bonis'),
                time=data.get('time'),
            )
            count += 1
    return count

def insert_general_time_results(rows, headers, stage, insert_batch_id):
    """Insère les résultats du classement général au temps"""
    from .models import GeneralTimeResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            GeneralTimeResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                bib=safe_int(data.get('bib')),
                h2h=safe_bool(data.get('h2h')),
                specialty=extract_specialty(cells[3] if len(cells) > 3 else None),
                age=safe_int(data.get('age')),
                rider=extract_rider_name(cells[5] if len(cells) > 5 else None),
                team=extract_team_name(cells[6] if len(cells) > 6 else None),
                uci=data.get('uci_pnt'),
                bonis=data.get('gc_bonis'),
                time=data.get('time'),
                time_wonlost=data.get('time_wonlost'),
            )
            count += 1
    return count

def insert_points_general_results(rows, headers, stage, insert_batch_id):
    """Insère les résultats du classement par points - General"""
    from .models import PointsGeneralResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            PointsGeneralResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                bib=safe_int(data.get('bib')),
                h2h=safe_bool(data.get('h2h')),
                specialty=extract_specialty(cells[3] if len(cells) > 3 else None),
                age=safe_int(data.get('age')),
                rider=extract_rider_name(cells[5] if len(cells) > 5 else None),
                team=extract_team_name(cells[6] if len(cells) > 6 else None),
                pnt=safe_int(data.get('pnt2')),
                today=data.get('delta_pnt'),
            )
            count += 1
    return count

def insert_points_today_results(rows, headers, stage, insert_batch_id):
    """Insère les résultats du classement par points - Today"""
    from .models import PointsTodayResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            PointsTodayResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                bib=safe_int(data.get('bib')),
                h2h=safe_bool(data.get('h2h')),
                specialty=extract_specialty(cells[3] if len(cells) > 3 else None),
                age=safe_int(data.get('age')),
                rider=extract_rider_name(cells[5] if len(cells) > 5 else None),
                team=extract_team_name(cells[6] if len(cells) > 6 else None),
                pnt=safe_int(data.get('pnt')),
                today=data.get('delta_pnt'),
            )
            count += 1
    return count

def insert_kom_general_results(rows, headers, stage, insert_batch_id):
    """Insère les résultats du classement KOM - General"""
    from .models import KOMGeneralResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            KOMGeneralResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                bib=safe_int(data.get('bib')),
                h2h=safe_bool(data.get('h2h')),
                specialty=extract_specialty(cells[3] if len(cells) > 3 else None),
                age=safe_int(data.get('age')),
                rider=extract_rider_name(cells[5] if len(cells) > 5 else None),
                team=extract_team_name(cells[6] if len(cells) > 6 else None),
                pnt=safe_int(data.get('pnt2')),
                today=data.get('delta_pnt'),
            )
            count += 1
    return count

def insert_kom_today_results(rows, headers, stage, insert_batch_id, kom_type):
    """Insère les résultats du classement KOM - Today"""
    from .models import KOMTodayResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            KOMTodayResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                bib=safe_int(data.get('bib')),
                h2h=safe_bool(data.get('h2h')),
                specialty=extract_specialty(cells[3] if len(cells) > 3 else None),
                age=safe_int(data.get('age')),
                rider=extract_rider_name(cells[5] if len(cells) > 5 else None),
                team=extract_team_name(cells[6] if len(cells) > 6 else None),
                pnt=safe_int(data.get('pnt')),
                today=data.get('delta_pnt'),
                kom_type=kom_type,
            )
            count += 1
    return count

def insert_youth_general_results(rows, headers, stage, insert_batch_id):
    """Insère les résultats du classement jeunes - General"""
    from .models import YouthGeneralResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            YouthGeneralResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                bib=safe_int(data.get('bib')),
                h2h=safe_bool(data.get('h2h')),
                specialty=extract_specialty(cells[3] if len(cells) > 3 else None),
                age=safe_int(data.get('age')),
                rider=extract_rider_name(cells[5] if len(cells) > 5 else None),
                team=extract_team_name(cells[6] if len(cells) > 6 else None),
                time=data.get('time'),
                time_wonlost=data.get('time_wonlost'),
            )
            count += 1
    return count

def insert_youth_today_results(rows, headers, stage, insert_batch_id):
    """Insère les résultats du classement jeunes - Today"""
    from .models import YouthTodayResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            YouthTodayResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                bib=safe_int(data.get('bib')),
                h2h=safe_bool(data.get('h2h')),
                specialty=extract_specialty(cells[3] if len(cells) > 3 else None),
                age=safe_int(data.get('age')),
                rider=extract_rider_name(cells[5] if len(cells) > 5 else None),
                team=extract_team_name(cells[6] if len(cells) > 6 else None),
                time=data.get('time'),
                time_wonlost=data.get('time_wonlost'),
            )
            count += 1
    return count

def insert_team_general_results(rows, headers, stage, insert_batch_id):
    """Insère les résultats du classement par équipes - General"""
    from .models import TeamGeneralResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            TeamGeneralResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                team=extract_team_name(cells[1] if len(cells) > 1 else None),
                time=data.get('time'),
                time_wonlost=data.get('time_wonlost'),
            )
            count += 1
    return count

def insert_team_today_results(rows, headers, stage, insert_batch_id):
    """Insère les résultats du classement par équipes - Today"""
    from .models import TeamTodayResult
    count = 0
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= len(headers):
            data = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    data[header] = cells[i].get_text(strip=True)
            
            TeamTodayResult.objects.create(
                stage=stage,
                insert_batch_id=insert_batch_id,
                rnk=safe_int(data.get('rnk')),
                team=extract_team_name(cells[1] if len(cells) > 1 else None),
                time=data.get('time'),
                time_wonlost=data.get('time_wonlost'),
            )
            count += 1
    return count

def extract_team_name(cell):
    """Extrait le nom de l'équipe d'une cellule"""
    if not cell:
        return None
    
    # Si c'est déjà une chaîne, on la retourne
    if isinstance(cell, str):
        return cell.strip()
    
    # Si c'est un objet BeautifulSoup, on extrait le texte du lien
    if hasattr(cell, 'find'):
        link = cell.find('a')
        if link:
            return link.get_text(strip=True)
        return cell.get_text(strip=True)
    
    return str(cell).strip()

def extract_specialty(cell):
    """Extrait la spécialité d'une cellule"""
    if not cell:
        return None
    
    # Si c'est déjà une chaîne, on la retourne
    if isinstance(cell, str):
        return cell.strip()
    
    # Si c'est un objet BeautifulSoup, on extrait le texte du span
    if hasattr(cell, 'find'):
        span = cell.find('span', class_='fs10')
        if span:
            return span.get_text(strip=True)
        return cell.get_text(strip=True)
    
    return str(cell).strip()

@admin.register(GeneralResult)
class GeneralResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "time", "time_wonlost", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(PointsResult)
class PointsResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "pnt", "today", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(FinishPointsResult)
class FinishPointsResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "pnt", "bonis", "today", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(KOMResult)
class KOMResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "pnt", "today", "kom_type", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty", "kom_type")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(GeneralTimeResult)
class GeneralTimeResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "time", "time_wonlost", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(YouthResult)
class YouthResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "time", "time_wonlost", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(StageGeneralResult)
class StageGeneralResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "gc", "timelag", "uci", "pnt", "bonis", "time", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(PointsGeneralResult)
class PointsGeneralResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "pnt", "today", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(PointsTodayResult)
class PointsTodayResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "pnt", "today", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(KOMGeneralResult)
class KOMGeneralResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "pnt", "today", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(KOMTodayResult)
class KOMTodayResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "pnt", "today", "kom_type", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty", "kom_type")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(YouthGeneralResult)
class YouthGeneralResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "time", "time_wonlost", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(YouthTodayResult)
class YouthTodayResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "bib", "rider", "team", "time", "time_wonlost", "specialty", "age", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team", "specialty")
    search_fields = ("rider", "team", "bib")
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(TeamGeneralResult)
class TeamGeneralResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "team", "time", "time_wonlost", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team")
    search_fields = ("team",)
    readonly_fields = ("insert_batch_id", "insert_date")

@admin.register(TeamTodayResult)
class TeamTodayResultAdmin(admin.ModelAdmin):
    list_display = ("rnk", "team", "time", "time_wonlost", "stage", "insert_batch_id", "insert_date")
    list_filter = ("stage", "team")
    search_fields = ("team",)
    readonly_fields = ("insert_batch_id", "insert_date")