"""
Service SOAP — Calcul de temps de trajet pour véhicules électriques.

Ce service expose une méthode SOAP `calculer_temps_trajet` qui prend en entrée
la distance du trajet, l'autonomie du véhicule et le temps de chargement,
et retourne le temps total de trajet, le coût estimé et le nombre d'arrêts.

Technologies :
- Spyne : Framework Python pour créer des services SOAP (génère le WSDL automatiquement)
- lxml : Parsing et validation XML (requis par Spyne)
- Gunicorn : Serveur WSGI de production (multi-worker)

Le WSDL est accessible via GET /?wsdl (géré par le wrapper WSGI `app()`).
Les requêtes SOAP (POST) sont déléguées à Spyne via `wsgi_app`.

Auteur : Tcha Jonathan — TP INFO802
"""

import os
from io import BytesIO
from lxml import etree
from spyne import Application, rpc, ServiceBase, Integer, Float, Unicode, ComplexModel
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
from spyne.interface.wsdl import Wsdl11


class ResultatTrajet(ComplexModel):
    """
    Structure de retour SOAP pour les résultats de calcul de trajet.

    Champs :
    - temps_total_heures : Durée totale du trajet (conduite + recharges) en heures
    - cout_total_euros   : Coût estimé en euros (basé sur 20 kWh/100km à 0.20 EUR/kWh)
    - nombre_arrets      : Nombre de pauses recharge nécessaires
    """
    temps_total_heures = Float
    cout_total_euros = Float
    nombre_arrets = Integer


class VehiculeElectriqueService(ServiceBase):
    """
    Service SOAP principal — Calcul de trajet pour véhicules électriques.

    Expose la méthode `calculer_temps_trajet` via le protocole SOAP 1.1.
    Le WSDL est généré automatiquement par Spyne à partir des annotations @rpc.

    Hypothèses de calcul :
    - Vitesse moyenne : 90 km/h (autoroute + routes nationales)
    - Consommation moyenne : 20 kWh/100km
    - Coût électricité : 0.20 EUR/kWh (tarif moyen borne publique)
    """

    @rpc(Float, Float, Integer, _returns=ResultatTrajet)
    def calculer_temps_trajet(ctx, distance_km, autonomie_km, temps_chargement_min):
        """
        Calcule le temps total de trajet incluant les arrêts de recharge.

        Algorithme :
        1. Temps de conduite = distance / vitesse_moyenne (90 km/h)
        2. Nombre d'arrêts = max(0, distance / autonomie - 1)
           → On soustrait 1 car le premier trajet part avec la batterie pleine
        3. Temps de recharge total = nombre_arrets * temps_chargement / 60
        4. Coût = distance / 100 * consommation * prix_kwh

        :param distance_km: Distance totale du trajet en kilomètres
        :param autonomie_km: Autonomie du véhicule en kilomètres
        :param temps_chargement_min: Temps pour une recharge complète en minutes
        :return: ResultatTrajet avec temps_total_heures, cout_total_euros, nombre_arrets
        """
        # --- Constantes de calcul ---
        vitesse_moyenne = 90.0       # km/h — moyenne autoroute + national
        cout_kwh = 0.20              # EUR/kWh — tarif moyen borne publique
        consommation_100km = 20.0    # kWh/100km — consommation moyenne VE

        # --- 1. Temps de conduite pur (sans arrêts) ---
        temps_conduite_h = distance_km / vitesse_moyenne

        # --- 2. Nombre d'arrêts nécessaires ---
        # On recharge quand on a parcouru "autonomie_km" km
        # Le -1 signifie qu'on part avec la batterie pleine (pas de recharge au départ)
        if autonomie_km > 0:
            nombre_arrets = max(0, int(distance_km / autonomie_km) - 1)
        else:
            nombre_arrets = 0

        # --- 3. Temps total de chargement (conversion minutes → heures) ---
        temps_chargement_total_h = (nombre_arrets * temps_chargement_min) / 60.0

        # --- 4. Temps total = conduite + recharges ---
        temps_total_h = temps_conduite_h + temps_chargement_total_h

        # --- 5. Coût total de l'électricité ---
        # Formule : (distance / 100) * consommation_par_100km * prix_par_kwh
        cout_total = (distance_km / 100.0) * consommation_100km * cout_kwh

        # --- Construction de la réponse SOAP ---
        resultat = ResultatTrajet()
        resultat.temps_total_heures = round(temps_total_h, 2)
        resultat.cout_total_euros = round(cout_total, 2)
        resultat.nombre_arrets = nombre_arrets

        return resultat


# --- Configuration de l'application Spyne ---
# tns = Target Namespace (identifiant unique du service SOAP)
# Soap11 = Protocole SOAP version 1.1 (le plus courant)
# validator='lxml' = Validation des requêtes XML entrantes
application = Application(
    [VehiculeElectriqueService],
    tns='vehicule.electrique.soap',
    in_protocol=Soap11(validator='lxml'),
    out_protocol=Soap11()
)

# Application WSGI Spyne (gère les requêtes SOAP POST)
wsgi_app = WsgiApplication(application)


def app(environ, start_response):
    """
    Wrapper WSGI qui sert le WSDL sur GET et délègue le SOAP sur POST.

    Pourquoi ce wrapper ?
    Spyne ne sert pas le WSDL automatiquement sur les requêtes GET.
    Ce wrapper intercepte les GET ?wsdl pour générer et retourner le WSDL
    dynamiquement, en utilisant l'URL du serveur actuel comme base.

    Pour les requêtes POST (appels SOAP normaux), on délègue à Spyne.

    :param environ: Variables d'environnement WSGI (méthode HTTP, URL, headers)
    :param start_response: Callback WSGI pour envoyer le status et les headers
    :return: Corps de la réponse HTTP (bytes)
    """
    query = environ.get('QUERY_STRING', '')
    method = environ.get('REQUEST_METHOD', 'GET')

    # --- Servir le WSDL sur GET ?wsdl ---
    if method == 'GET' and 'wsdl' in query.lower():
        # Construire l'URL de base à partir des headers HTTP
        url = environ.get('HTTP_HOST', 'localhost')
        scheme = environ.get('wsgi.url_scheme', 'https')
        base_url = f"{scheme}://{url}/"

        # Générer le WSDL via Spyne
        wsdl = Wsdl11(application.interface)
        wsdl.build_interface_document(base_url)
        wsdl_doc = wsdl.get_interface_document()

        # Sérialiser en bytes si nécessaire (lxml retourne un Element, pas des bytes)
        if isinstance(wsdl_doc, etree._Element):
            wsdl_bytes = etree.tostring(wsdl_doc, xml_declaration=True, encoding='UTF-8')
        else:
            wsdl_bytes = wsdl_doc

        # Retourner le WSDL en XML
        start_response('200 OK', [
            ('Content-Type', 'text/xml; charset=utf-8'),
            ('Content-Length', str(len(wsdl_bytes)))
        ])
        return [wsdl_bytes]

    # --- Pour tout le reste (POST SOAP), déléguer à Spyne ---
    return wsgi_app(environ, start_response)


# --- Point d'entrée pour le développement local ---
if __name__ == '__main__':
    from wsgiref.simple_server import make_server

    port = int(os.environ.get('SOAP_PORT', 8000))
    server = make_server('0.0.0.0', port, app)

    print(f"Service SOAP demarré sur http://localhost:{port}")
    print(f"WSDL disponible sur http://localhost:{port}/?wsdl")

    server.serve_forever()
