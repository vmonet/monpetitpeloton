from django import forms
from .models import StageSelection, Cyclist, BonusConfig, StageSelectionBonus

class StageSelectionForm(forms.ModelForm):
    """
    Form for selecting up to 8 riders for a stage and distributing bonuses.
    Only allows riders from the validated team.
    The roles (leader, sprinteur, grimpeur) are handled via extra fields in the template/POST.
    """
    riders = forms.ModelMultipleChoiceField(
        queryset=Cyclist.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Select up to 8 riders"
    )

    def __init__(self, *args, **kwargs):
        team = kwargs.pop('team', None)
        stage = kwargs.pop('stage', None)
        competition = kwargs.pop('competition', None)
        super().__init__(*args, **kwargs)
        if team:
            self.fields['riders'].queryset = Cyclist.objects.filter(team_cyclists__team=team)
        # Bonus fields (one int field per bonus config)
        self.bonus_fields = []
        if competition:
            for bonus in BonusConfig.objects.filter(competition=competition):
                field_name = f'bonus_{bonus.id}'
                self.fields[field_name] = forms.IntegerField(
                    min_value=0,
                    max_value=bonus.max_per_player,
                    required=False,
                    label=f"{bonus.name} (max {bonus.max_per_player})"
                )
                self.bonus_fields.append((field_name, bonus))

    class Meta:
        model = StageSelection
        fields = ['riders']

    def clean(self):
        cleaned = super().clean()
        riders = cleaned.get('riders')
        if riders:
            if len(riders) != 8:
                self.add_error('riders', "You must select exactly 8 riders.")
        # Bonus validation
        total_bonus = 0
        for field_name, bonus in getattr(self, 'bonus_fields', []):
            val = self.cleaned_data.get(field_name, 0) or 0
            if val > bonus.max_per_player:
                self.add_error(field_name, f"Max {bonus.max_per_player} for {bonus.name}.")
            total_bonus += val
        # Les rôles seront validés dans la vue
        return cleaned