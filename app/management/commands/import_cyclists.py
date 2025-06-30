import csv
from django.core.management.base import BaseCommand
from app.models import Cyclist

class Command(BaseCommand):
    help = 'Importe les cyclistes depuis un fichier CSV'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Chemin vers le fichier CSV')

    def handle(self, *args, **kwargs):
        csv_file = kwargs['csv_file']
        with open(csv_file, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                cycliste, created = Cyclist.objects.get_or_create(
                    name=row['Coureur'],
                    defaults={
                        'team': row['Équipe'],
                        'value': row['Prix min'],
                    }
                )
                count += 1 if created else 0
        self.stdout.write(self.style.SUCCESS(f"{count} cyclistes importés."))
