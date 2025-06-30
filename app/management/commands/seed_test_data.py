import random
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from app.models import Competition, Stage, League, Team, Cyclist, TeamCyclist, LeagueAuction, TeamCyclistAuction, LeagueRound, resolve_auctions_for_league

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database with test data: 1 competition, 21 stages, 5 users/teams, and 4 rounds of auctions.'

    @transaction.atomic
    def handle(self, *args, **options):
        # 1. Delete all "special" cyclists created in previous runs
        self.stdout.write("Deleting special cyclists...")
        Cyclist.objects.filter(name__icontains="Test Cyclist").delete()  # Assuming "Cyclist" in the name is used for special cyclists

        self.stdout.write("Deleting old data...")
        Stage.objects.all().delete()
        League.objects.all().delete() # Deletes Teams, Auctions, etc. via cascades
        Competition.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()
        # Keep cyclists, assuming they are seeded from another source

        self.stdout.write("Creating new data...")

        # 2. Create Users
        users = []
        for i in range(5):
            username = f'player{i+1}'
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password('password')  # Securely set the password
                user.save()
            users.append(user)
        
        creator_user = users[0]

        # 3. Create Competition and Stages
        competition = Competition.objects.create(name="Tour de Test 2024")
        start_date = date.today()
        for i in range(21):
            Stage.objects.create(
                competition=competition,
                name=f"Stage {i+1}: From A to B",
                date=start_date + timedelta(days=i)
            )

        # 4. Create League and Teams
        league = League.objects.create(name="Test League", creator=creator_user, competition=competition)
        teams = [Team.objects.create(player=user, league=league) for user in users]

        # Add admin user if present
        admin_user = User.objects.filter(is_superuser=True).first()
        if admin_user and not Team.objects.filter(player=admin_user, league=league).exists():
            Team.objects.create(player=admin_user, league=league)
            users.append(admin_user)
            self.stdout.write(self.style.SUCCESS("Admin user added to the league."))

        # Activate the league
        league.is_active = True
        league.save()
        self.stdout.write(self.style.SUCCESS("League is now active."))

        # 5. Simulate auction rounds until all teams have 12 cyclists
        available_cyclists = list(Cyclist.objects.all())
        if not available_cyclists:
            self.stdout.write(self.style.ERROR("No cyclists found. Please seed cyclists first."))
            return

        teams = list(Team.objects.filter(league=league))
        round_number = 1
        while True and round_number < 10:
            self.stdout.write(f"--- Simulating Round {round_number} ---")
            current_round, created = LeagueRound.objects.get_or_create(
                league=league,
                round_number=round_number,
                defaults={'competition': competition}
            )
            all_finished = True
            for team in teams:
                owned_cyclists = TeamCyclist.objects.filter(team=team, league=league)
                spent = sum(c.price for c in owned_cyclists)
                remaining_budget = 488 - spent  # Budget starting at 488
                num_owned = owned_cyclists.count()
                if num_owned >= 12 or remaining_budget <= 0:
                    continue
                all_finished = False
                auction = LeagueAuction.objects.create(league=league, team=team, round_number=round_number)
                
                # Correctly calculate the number of cyclists to bid on
                remaining_spots = 12 - num_owned
                cyclists_to_bid_on = 12
                
                bids_to_create = []
                for _ in range(cyclists_to_bid_on):
                    random.shuffle(available_cyclists)
                    chosen_cyclist = None
                    for cyclist in available_cyclists:
                        if not TeamCyclist.objects.filter(league=league, cyclist=cyclist).exists():
                            chosen_cyclist = cyclist
                            break
                    if not chosen_cyclist:
                        continue
                    max_bid = remaining_budget - (len(bids_to_create) * chosen_cyclist.value)
                    if max_bid < chosen_cyclist.value:
                        continue
                    price = random.randint(chosen_cyclist.value, max_bid)
                    bids_to_create.append(
                        TeamCyclistAuction(league_auction=auction, cyclist=chosen_cyclist, price=price, status='pending')
                    )
                    remaining_budget -= price
                if bids_to_create:
                    TeamCyclistAuction.objects.bulk_create(bids_to_create)
                    self.stdout.write(f"Team {team.player.username} submitted {len(bids_to_create)} bids.")
            self.stdout.write(f"Resolving auctions for round {round_number}...")
            resolve_auctions_for_league(league.id, round_number)
            # Check if all teams are finished
            if all_finished:
                break
            round_number += 1

        # Ensure all teams have 12 cyclists, if not, create them and bid for them
        for team in teams:
            num_owned = TeamCyclist.objects.filter(team=team, league=league).count()
            remaining_spots = 12 - num_owned
            if remaining_spots > 0:
                self.stdout.write(self.style.WARNING(f"Team {team.player.username} has only {num_owned} cyclists, adding {remaining_spots} more."))
                
                # 6. Create missing cyclists for the team
                new_cyclists = []
                for _ in range(remaining_spots):
                    new_cyclist = Cyclist.objects.create(name=f"Test Cyclist {team.player.username}-{random.randint(1000, 9999)}", value=1)
                    new_cyclists.append(new_cyclist)
                
                # Create a special auction for these cyclists
                auction = LeagueAuction.objects.create(league=league, team=team, round_number=round_number)
                bids_to_create = []
                for i, cyclist in enumerate(new_cyclists):
                    price = 1 if i < len(new_cyclists) - 1 else remaining_budget  # Last cyclist uses all remaining budget
                    bids_to_create.append(
                        TeamCyclistAuction(league_auction=auction, cyclist=cyclist, price=price, status='pending')
                    )
                    remaining_budget -= price
                
                if bids_to_create:
                    TeamCyclistAuction.objects.bulk_create(bids_to_create)
                    self.stdout.write(f"Team {team.player.username} submitted {len(bids_to_create)} special bids.")
        
        # Resolving the final round of auctions for the missing cyclists
        self.stdout.write("Resolving final round of auctions...")
        resolve_auctions_for_league(league.id, round_number)

        self.stdout.write(self.style.SUCCESS("All teams have 12 cyclists. Seeding complete.")) 
