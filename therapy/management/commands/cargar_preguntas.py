from django.core.management.base import BaseCommand
from therapy.models import AssessmentQuestion, AssessmentSection, Category

class Command(BaseCommand):
    help = 'Carga preguntas de evaluación desde código.'

    def handle(self, *args, **kwargs):
        # Asegúrate de que estas secciones y categorías existen antes
        seccion_1 = AssessmentSection.objects.get(title="Inicio")  # ajusta el nombre
        ansiedad = Category.objects.get(name="Ansiedad")
        motivacion = Category.objects.get(name="Motivación")

        preguntas = [
            {
                "section": seccion_1,
                "category": ansiedad,
                "text": "¿Con qué frecuencia te sientes nervioso o tenso sin razón aparente?",
                "question_type": "choice",
                "options": ["Nunca", "A veces", "Frecuentemente", "Siempre"],
                "allow_multiple": False,
                "order": 1,
            },
            {
                "section": seccion_1,
                "category": motivacion,
                "text": "¿Qué te motiva a seguir adelante cuando las cosas se ponen difíciles?",
                "question_type": "text",
                "allow_multiple": False,
                "order": 2,
            }
        ]

        for p in preguntas:
            pregunta, created = AssessmentQuestion.objects.get_or_create(
                section=p["section"],
                category=p["category"],
                text=p["text"],
                defaults={
                    "question_type": p["question_type"],
                    "options": p.get("options"),
                    "allow_multiple": p["allow_multiple"],
                    "order": p["order"],
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Pregunta creada: {pregunta.text}'))
            else:
                self.stdout.write(f'Ya existe: {pregunta.text}')
