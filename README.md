# Deprescriptor

## Description
Ce projet est une app nicegui qui se comporte de la façon suivante:
un dataframe polars est charge, il contient une seule colonne 'IEP'
L'application presente un formulaire dans lequel il est possible de saisir un IEP ou de le selectionner dans une liste deroulante
Puis on a un champ de texte destiner a revevoir le texte dune ordonnance
un autre champ pour saisir les medicament arretes avec possibilite d'arreter plus d'un medicament
pour chaque medoc arrete la possibilite de choisir une ou plusieurs des justifications suivantes:
  - Absence d'indication (jamais indique)
  - Absence d'indication (n'est plus indique mais non arrete)
  - Presence de contre indication
  - Presence d'une interaction medicamenteuse
  - Survenue d'un effet indesirable
  - Autre (libre)

Si contre indication, interaction medicamenteuse ou effet indesirable, ajouter un champ texte pour preciser la nature du truc

un bouton pour valider le formulaire

L'app doit stocker les reponses dans un fichier csv avec l'iep et la date de validation du formulaire

le chargement des donnees se fait pour l'instant depuis un fichier csv test_data.csv pour le dev de l'app
