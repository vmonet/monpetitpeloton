#!/bin/bash

echo "🚴‍♂️ Seeding Django fantasy cycling DB..."

python manage.py shell <<EOF
import random
from django.contrib.auth import get_user_model
from app.models import Competition, League, Membership, Cyclist

User = get_user_model()

# 1. Create a competition if it doesn't exist
comp_name = "Fantasy Tour"
comp, created = Competition.objects.get_or_create(name=comp_name)
if created:
    print(f"✅ Competition created: {comp.name}")
else:
    print(f"ℹ️ Competition already exists: {comp.name}")

# 2. Create a league linked to the competition
league_name = "Official League"
league, created = League.objects.get_or_create(name=league_name, competition=comp, creator_id=1)  # temp creator_id
if created:
    print(f"✅ League created: {league.name}")
else:
    print(f"ℹ️ League already exists: {league.name}")

# 3. Create users
users = []
for i in range(1, 3):
    username = f"user{i}"
    email = f"user{i}@example.com"
    user, _ = User.objects.get_or_create(username=username, defaults={"email": email})
    user.set_password("test1234")
    user.save()
    users.append(user)
    print(f"👤 User created or exists: {user.username}")

# 4. Set the first user as league creator
league.creator = users[0]
league.save()

# 5. Add users to the league
for user in users:
    m, created = Membership.objects.get_or_create(user=user, league=league)
    if created:
        print(f"🔗 {user.username} joined {league.name}")

# 6. Generate 100 cyclists
existing = Cyclist.objects.count()
if existing < 100:
    teams = ["Team A", "Team B", "Team C", "Team D", "Team E"]
    nationalities = ["FR", "BE", "NL", "IT", "ES"]
    for i in range(100):
        Cyclist.objects.create(
            name=f"Cyclist {i+1}",
            team=random.choice(teams),
            nationality=random.choice(nationalities),
            value=round(random.uniform(1, 15), 0)
        )
    print("🚴‍♀️ 100 cyclists created")
else:
    print(f"ℹ️ {existing} cyclists already exist")
EOF

echo "✅ Done."
