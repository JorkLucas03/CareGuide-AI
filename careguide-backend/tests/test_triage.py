import unittest

from app.services.triage import analyze_message, estimate_specialty, normalize_text


class TriageSpecialtyTests(unittest.TestCase):
    def test_uses_latest_clinical_focus_from_accumulated_chat(self):
        text = (
            "Recomendacion de hospital para chequeo general. "
            "Me duele el pene. "
            "Y tambien me duele la cabeza. "
            "Me va a dar un paro cardiaco."
        )

        result = analyze_message(text)

        self.assertEqual(result.specialty, "Cardiologia")
        self.assertEqual(result.urgency_level, 5)

    def test_urology_detects_genital_pain(self):
        result = analyze_message("Me duele el pene")

        self.assertEqual(result.specialty, "Urologia")
        self.assertGreaterEqual(result.urgency_level, 2)

    def test_latest_symptom_wins_when_multiple_specialties_are_present(self):
        specialty = estimate_specialty(normalize_text("Me duele el pene y tambien me duele la cabeza"))

        self.assertEqual(specialty, "Neurologia")


if __name__ == "__main__":
    unittest.main()
