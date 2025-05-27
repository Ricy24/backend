# backend/chat/services.py
import os
import logging
import json
from groq import Groq
from django.conf import settings
from .models import CoachingMensaje, CoachingSession, CoachingMeta

logger = logging.getLogger(__name__)

class GroqCoachingService:
    def __init__(self, api_key=None):
        self.api_key = api_key or getattr(settings, 'GROQ_API_KEY', None)
        
        if not self.api_key:
            logger.critical("GROQ_API_KEY no está configurada en settings.py o variables de entorno.")
            raise ValueError("GROQ_API_KEY no está configurada.")
        
        self.client = Groq(api_key=self.api_key) # Inicialización del cliente Groq

        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "sugerir_sub_meta",
                    "description": "Usar esta función cuando identifiques una posible sub-meta o paso accionable claro que el usuario ha mencionado o que se deriva lógicamente de la conversación y su objetivo principal. Formula la sub-meta de forma concisa y accionable.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "descripcion_sub_meta": {
                                "type": "string",
                                "description": "La descripción clara y accionable de la sub-meta sugerida (ej: 'Investigar 3 técnicas de estudio efectivas', 'Dedicar 20 minutos diarios a practicar vocabulario').",
                            },
                            "razonamiento_breve": {
                                "type": "string",
                                "description": "Una breve explicación (1 frase) de por qué esta sub-meta es relevante para el objetivo principal del usuario."
                            }
                        },
                        "required": ["descripcion_sub_meta"],
                    },
                },
            }
        ]

    def _construir_historial_para_groq(self, sesion_coaching: CoachingSession, mensajes_de_interaccion_actual: list, max_mensajes_db=10):
        # Obtener mensajes de la base de datos
        limite_db = max(0, max_mensajes_db) 
        mensajes_db_obj = CoachingMensaje.objects.filter(
            sesion=sesion_coaching
        ).order_by('-timestamp')[:limite_db]
        
        mensajes_db_formateados_para_historial = []
        for msg_db in reversed(list(mensajes_db_obj)):
            role = "assistant" if msg_db.es_respuesta_ia else "user"
            content_to_add = msg_db.contenido
            
            if msg_db.es_respuesta_ia and not content_to_add:
                content_to_add = "" # Si la IA solo hizo un tool_call y no hubo content.
            
            mensajes_db_formateados_para_historial.append({"role": role, "content": content_to_add})

        # ----- PROMPT DE SISTEMA -----
        # Asegúrate de que este prompt sea detallado y guíe bien a la IA
        system_prompt_content = (
            f"Eres Senti Coach, un coach de IA avanzado, empático y estratégico. Tu misión es ayudar al usuario a alcanzar su meta principal: '{sesion_coaching.objetivo_principal}'.\n"
            f"Habla de forma cercana y motivadora.\n\n"
            f"METODOLOGÍA:\n"
            f"1. Si la meta principal es nueva o vaga, ayúdalo a clarificarla (¿Qué aspecto específico? ¿Cómo se ve el éxito?).\n"
            f"2. Pregunta por su motivación y un plazo general.\n"
            f"3. Guíalo para identificar pequeños pasos o sub-metas. Cuando identifiques una sub-meta clara (específica, medible, accionable) que se derive de la conversación o su objetivo, USA la herramienta `sugerir_sub_meta` para proponerla formalmente. Explica brevemente por qué la sugieres.\n"
            f"   Ejemplo de uso de herramienta: si el usuario quiere 'aprender inglés' y dice 'debería empezar por lo básico', podrías usar `sugerir_sub_meta` con `descripcion_sub_meta: 'Estudiar las 100 palabras más comunes en inglés'` y un `razonamiento_breve`.\n"
            f"4. Después de usar la herramienta `sugerir_sub_meta`, tu turno en ESA respuesta termina. El sistema te informará si el usuario aceptó o rechazó.\n"
            f"5. SI EL USUARIO ACEPTA una sub-meta, ya está en el plan. Continúa la conversación: felicítalo, pregunta cómo se siente al respecto, si quiere enfocarse en ella ahora, o cuál sería el siguiente paso. NO vuelvas a sugerir la misma meta.\n"
            f"6. SI EL USUARIO RECHAZA una sub-meta, acéptalo con naturalidad. Pregunta cómo le gustaría proceder o si tiene otras ideas. NO insistas.\n"
            f"7. Si no hay una sub-meta clara para proponer con la herramienta, simplemente continúa la conversación de coaching normal, haciendo preguntas, ofreciendo apoyo o sugiriendo tipos de recursos genéricos que el usuario puede buscar.\n\n"
            f"SUB-METAS DEL USUARIO (ya en el plan):\n"
        )
        sub_metas_activas = CoachingMeta.objects.filter(sesion=sesion_coaching, completada=False).order_by('id')
        if sub_metas_activas.exists():
            system_prompt_content += "El usuario tiene estas sub-metas activas. Considera su progreso en ellas:\n"
            for meta in sub_metas_activas:
                system_prompt_content += f"  - {meta.descripcion}\n"
        else:
            system_prompt_content += "Actualmente no hay sub-metas activas registradas. Ayúdalo a definir los primeros pasos.\n\n"
        
        system_prompt_content += (
             f"INSTRUCCIONES FINALES:\n"
             f"- Enfócate en el paso actual. Sé práctico.\n"
             f"- Si usas `sugerir_sub_meta`, no añadas más texto en esa respuesta.\n"
             f"- Adapta tu conversación al último mensaje del usuario y al historial."
        )
        
        historial_completo = [{"role": "system", "content": system_prompt_content}]
        historial_completo.extend(mensajes_db_formateados_para_historial)
        historial_completo.extend(mensajes_de_interaccion_actual) 
            
        # logger.debug(f"Historial para Groq (len: {len(historial_completo)}): {json.dumps(historial_completo, indent=2, ensure_ascii=False)}")
        return historial_completo

    def obtener_respuesta_coach(self, sesion_coaching: CoachingSession, mensaje_usuario_contenido: str, max_tool_iterations=1):
        # Guardar mensaje del usuario que inició esta interacción
        CoachingMensaje.objects.create(
            sesion=sesion_coaching,
            contenido=mensaje_usuario_contenido,
            es_respuesta_ia=False
        )

        conversation_messages_for_groq = [{"role": "user", "content": mensaje_usuario_contenido}]
        mensaje_para_frontend = None

        for iteration in range(max_tool_iterations):
            historial_groq = self._construir_historial_para_groq(sesion_coaching, conversation_messages_for_groq)

            try:
                logger.info(f"Llamando a Groq (iteración {iteration+1}) para sesión {sesion_coaching.id}. Modelo: llama3-70b-8192")
                chat_completion = self.client.chat.completions.create(
                    messages=historial_groq,
                    model="llama3-70b-8192", 
                    temperature=0.6,
                    max_tokens=1500,
                    tools=self.tools,
                    tool_choice="auto" 
                )
                
                response_message_from_groq = chat_completion.choices[0].message
                tool_calls = response_message_from_groq.tool_calls

                # Preparar para añadir la respuesta de la IA (con o sin tool_calls) al historial de esta interacción
                current_ia_response_for_groq_hist = {"role": "assistant"}
                if response_message_from_groq.content: # Puede haber content Y tool_calls
                    current_ia_response_for_groq_hist["content"] = response_message_from_groq.content
                
                if tool_calls:
                    current_ia_response_for_groq_hist["tool_calls"] = [
                        {"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in tool_calls
                    ]
                
                # Solo añadir al historial si hay algo que añadir (content o tool_calls)
                if "content" in current_ia_response_for_groq_hist or "tool_calls" in current_ia_response_for_groq_hist:
                    conversation_messages_for_groq.append(current_ia_response_for_groq_hist)


                if tool_calls:
                    logger.info(f"IA solicitó usar herramientas: {[tc.function.name for tc in tool_calls]}")
                    # Asumimos que `sugerir_sub_meta` es la única herramienta por ahora
                    first_tool_call = tool_calls[0] 
                    function_name = first_tool_call.function.name

                    if function_name == "sugerir_sub_meta":
                        try:
                            function_args = json.loads(first_tool_call.function.arguments)
                        except json.JSONDecodeError as e:
                            logger.error(f"Error decodificando args JSON para {function_name}: {first_tool_call.function.arguments}. E: {e}")
                            mensaje_para_frontend = CoachingMensaje.objects.create(sesion=sesion_coaching, contenido="Tuve una idea, pero hubo un error al procesarla. ¿Podemos intentarlo de nuevo o probar otra cosa?", es_respuesta_ia=True)
                            break 

                        descripcion_sugerida = function_args.get("descripcion_sub_meta")
                        razonamiento = function_args.get("razonamiento_breve", "")

                        if not descripcion_sugerida:
                            logger.error(f"Tool call 'sugerir_sub_meta' sin 'descripcion_sub_meta'. Args: {function_args}")
                            mensaje_para_frontend = CoachingMensaje.objects.create(sesion=sesion_coaching, contenido="Intenté sugerir un paso, pero faltó información. ¿Podrías decirme más sobre lo que piensas?", es_respuesta_ia=True)
                            break

                        logger.info(f"IA sugirió sub-meta: '{descripcion_sugerida}'")
                        
                        texto_presentacion_sugerencia = response_message_from_groq.content or \
                                                       f"Analizando nuestra conversación, se me ocurre que un buen paso podría ser: '{descripcion_sugerida}'."
                        if razonamiento and not response_message_from_groq.content:
                            texto_presentacion_sugerencia += f" Considero que esto te ayudaría porque {razonamiento.lower()}."
                        if not any(q_word in texto_presentacion_sugerencia.lower() for q_word in ["¿qué te parece?", "te gustaría añadirlo", "quieres considerarlo"]):
                           texto_presentacion_sugerencia += f" ¿Te gustaría añadir esto a tu plan?"
                        
                        mensaje_para_frontend = CoachingMensaje.objects.create(
                            sesion=sesion_coaching,
                            contenido=texto_presentacion_sugerencia,
                            es_respuesta_ia=True
                        )
                        mensaje_para_frontend.metadata_para_frontend = {
                            'sugerencia_sub_meta': {
                                'descripcion': descripcion_sugerida,
                                'razonamiento': razonamiento,
                                'tool_call_id': first_tool_call.id 
                            }
                        }
                        break 
                    else: 
                        logger.warning(f"Herramienta desconocida solicitada: {function_name}. Informando a la IA.")
                        conversation_messages_for_groq.append({"tool_call_id": first_tool_call.id, "role": "tool", "name": function_name, "content": f"Error: Herramienta '{function_name}' no implementada."})
                        # Si es la última iteración y la IA no dio respuesta de texto, generamos un error.
                        if iteration == max_tool_iterations - 1 and not response_message_from_groq.content:
                             mensaje_para_frontend = CoachingMensaje.objects.create(sesion=sesion_coaching, contenido="Intenté algo que no sé hacer. ¿Podríamos continuar de otra manera?", es_respuesta_ia=True)
                             break
                        # Si no es la última iteración, el bucle continuará y la IA debería generar una respuesta basada en el error de la tool.

                else: # No hay tool_calls, respuesta de texto directa
                    respuesta_ia_contenido = response_message_from_groq.content.strip() if response_message_from_groq.content else ""
                    if not respuesta_ia_contenido:
                        logger.warning(f"Respuesta vacía de IA sin tool_call para sesión {sesion_coaching.id}.")
                        respuesta_ia_contenido = "Hmm, no estoy seguro de cómo continuar. ¿Podrías reformular?"
                    
                    mensaje_para_frontend = CoachingMensaje.objects.create(
                        sesion=sesion_coaching,
                        contenido=respuesta_ia_contenido,
                        es_respuesta_ia=True
                    )
                    break 
            except Exception as e:
                logger.error(f"Excepción en llamada a Groq o proc. herramienta (Sesión {sesion_coaching.id}): {e}", exc_info=True)
                mensaje_para_frontend = CoachingMensaje.objects.create(sesion=sesion_coaching, contenido="Lo siento, ocurrió un error técnico al procesar tu mensaje. Intenta de nuevo.", es_respuesta_ia=True)
                break
        
        if not mensaje_para_frontend: # Fallback si el bucle termina sin mensaje
            logger.error(f"No se generó respuesta final tras {max_tool_iterations} iteraciones (Sesión {sesion_coaching.id}).")
            mensaje_para_frontend = CoachingMensaje.objects.create(sesion=sesion_coaching, contenido="Parece que me he quedado sin palabras. ¿Podemos reiniciar esta parte?", es_respuesta_ia=True)
            
        return mensaje_para_frontend

    def confirmar_creacion_sub_meta(self, sesion_coaching: CoachingSession, descripcion_sub_meta_original: str, aceptada: bool, tool_call_id_original: str = None):
        if aceptada:
            meta_creada = CoachingMeta.objects.create(sesion=sesion_coaching, descripcion=descripcion_sub_meta_original)
            logger.info(f"Sub-meta ACEPTADA y creada (ID: {meta_creada.id}): '{descripcion_sub_meta_original}'")
            # Mensaje que el *usuario* efectivamente envió (o se infiere de su acción)
            # Esto es importante para el historial de la IA
            CoachingMensaje.objects.create(sesion=sesion_coaching, contenido=f"(Decisión sobre sugerencia: Acepté añadir '{descripcion_sub_meta_original}')", es_respuesta_ia=False)
            tool_response_content_for_history = f"El usuario ACEPTÓ la sugerencia de la sub-meta: '{descripcion_sub_meta_original}'. Ya está en el plan."
            ia_fallback_message = f"¡Excelente! '{descripcion_sub_meta_original}' se ha añadido a tu plan. ¿En qué te gustaría que nos enfoquemos ahora?"
        else:
            logger.info(f"Sub-meta RECHAZADA: '{descripcion_sub_meta_original}'")
            CoachingMensaje.objects.create(sesion=sesion_coaching, contenido=f"(Decisión sobre sugerencia: Rechacé añadir '{descripcion_sub_meta_original}')", es_respuesta_ia=False)
            tool_response_content_for_history = f"El usuario RECHAZÓ la sugerencia de la sub-meta: '{descripcion_sub_meta_original}'."
            ia_fallback_message = f"Entendido, no hemos añadido '{descripcion_sub_meta_original}'. ¿Sobre qué te gustaría que conversemos ahora o qué otro paso tienes en mente?"

        # Mensajes para la siguiente llamada a Groq: la respuesta simulada de la herramienta
        mensajes_interaccion_para_groq = []
        if tool_call_id_original: # Si tenemos el ID del tool_call original, usamos el formato completo
            mensajes_interaccion_para_groq.append({
                "tool_call_id": tool_call_id_original,
                "role": "tool",
                "name": "sugerir_sub_meta", 
                "content": tool_response_content_for_history,
            })
        else: # Si no, al menos pasamos el contenido como si fuera una respuesta de tool
            logger.warning(f"No se proporcionó tool_call_id_original para la confirmación de '{descripcion_sub_meta_original}'. La IA podría no tener el contexto completo del tool_call.")
            mensajes_interaccion_para_groq.append({
                "role": "assistant", # Simular que es parte de la respuesta anterior de la IA
                "content": f"(Internamente, la sugerencia '{descripcion_sub_meta_original}' fue { 'aceptada' if aceptada else 'rechazada' } por el usuario.)"
            })


        # Obtener la siguiente respuesta de la IA ahora que conoce la decisión del usuario
        historial_para_groq = self._construir_historial_para_groq(
            sesion_coaching, 
            mensajes_de_interaccion_actual=mensajes_interaccion_para_groq
        )
        
        try:
            logger.debug(f"Enviando a Groq para respuesta post-confirmación. Historial (últimos mensajes de interacción): {mensajes_interaccion_para_groq}")
            chat_completion = self.client.chat.completions.create(
                messages=historial_para_groq,
                model="llama3-8b-8192", 
                temperature=0.7,
                max_tokens=1024,
            )
            respuesta_ia_contenido = chat_completion.choices[0].message.content.strip()
            if not respuesta_ia_contenido:
                respuesta_ia_contenido = ia_fallback_message
        except Exception as e:
            logger.error(f"Error obteniendo respuesta de IA post-confirmación (Sesión {sesion_coaching.id}): {e}", exc_info=True)
            respuesta_ia_contenido = ia_fallback_message

        mensaje_ia_obj = CoachingMensaje.objects.create(
            sesion=sesion_coaching,
            contenido=respuesta_ia_contenido,
            es_respuesta_ia=True
        )
        logger.info(f"Respuesta de IA post-confirmación (ID: {mensaje_ia_obj.id}) guardada: '{respuesta_ia_contenido[:50]}...'")
        return mensaje_ia_obj