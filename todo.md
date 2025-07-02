- inscription des gens
- vue résultats enchères
- Nom de l'équipe quand on join une ligue
- Worker
- Dans la sélection team étape on peut cliquer sur leader meme si le coureur n'est pas sélecionné
- Ordonner la sélection par ordre des rôles dans le peleton
- Afficher mieux l'équipe à droite

## Resultats

- Créer une 2 base de données Render
- Bucket GCP pour stocker les résultats html
- Script pour charger le html, le parser en CSV et stocker le résultats dans GCP --> déploiement via une cloud fonction
- Script pour envoyer le CSV dans un modèle de la BDD --> déploiement via une cloud fonction
- Page d'affichage résultats étapes