import os
from io import BytesIO
from lxml import etree
from spyne import Application, rpc, ServiceBase, Integer, Float, Unicode, ComplexModel
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
from spyne.interface.wsdl import Wsdl11

class ResultatTrajet(ComplexModel):
    """Structure de retour pour les résultats de calcul"""
    temps_total_heures = Float
    cout_total_euros = Float
    nombre_arrets = Integer

class VehiculeElectriqueService(ServiceBase):
    """
    Service SOAP pour calculer le temps et le coût d'un trajet en véhicule électrique.

    Prend en compte:
    - La distance du trajet (en km)
    - L'autonomie du véhicule (en km)
    - Le temps de chargement (en minutes)

    Retourne le temps total de trajet et le coût.
    """

    @rpc(Float, Float, Integer, _returns=ResultatTrajet)
    def calculer_temps_trajet(ctx, distance_km, autonomie_km, temps_chargement_min):
        """
        Calcule le temps total de trajet et le coût incluant les arrêts de recharge.

        :param distance_km: Distance totale du trajet en kilomètres
        :param autonomie_km: Autonomie du véhicule en kilomètres
        :param temps_chargement_min: Temps nécessaire pour une recharge complète en minutes
        :return: Résultat avec temps total et coût
        """
        # Vitesse moyenne estimée (km/h)
        vitesse_moyenne = 90.0

        # Temps de conduite pur (sans arrêts)
        temps_conduite_h = distance_km / vitesse_moyenne

        # Nombre d'arrêts nécessaires pour recharger
        if autonomie_km > 0:
            nombre_arrets = max(0, int(distance_km / autonomie_km) - 1)
        else:
            nombre_arrets = 0

        # Temps total de chargement en heures
        temps_chargement_total_h = (nombre_arrets * temps_chargement_min) / 60.0

        # Temps total
        temps_total_h = temps_conduite_h + temps_chargement_total_h

        # Calcul du coût
        # Coût électricité par kWh (€)
        cout_kwh = 0.20
        # Consommation moyenne (kWh/100km)
        consommation_100km = 20.0
        # Coût total = distance * consommation * prix kWh
        cout_total = (distance_km / 100.0) * consommation_100km * cout_kwh

        resultat = ResultatTrajet()
        resultat.temps_total_heures = round(temps_total_h, 2)
        resultat.cout_total_euros = round(cout_total, 2)
        resultat.nombre_arrets = nombre_arrets

        return resultat

application = Application([VehiculeElectriqueService],
    tns='vehicule.electrique.soap',
    in_protocol=Soap11(validator='lxml'),
    out_protocol=Soap11()
)

wsgi_app = WsgiApplication(application)

def app(environ, start_response):
    """Wrapper WSGI qui sert le WSDL sur GET ?wsdl"""
    query = environ.get('QUERY_STRING', '')
    method = environ.get('REQUEST_METHOD', 'GET')

    if method == 'GET' and 'wsdl' in query.lower():
        # Générer le WSDL dynamiquement
        url = environ.get('HTTP_HOST', 'localhost')
        scheme = environ.get('wsgi.url_scheme', 'https')
        base_url = f"{scheme}://{url}/"

        wsdl = Wsdl11(application.interface)
        wsdl.build_interface_document(base_url)
        wsdl_doc = wsdl.get_interface_document()

        if isinstance(wsdl_doc, etree._Element):
            wsdl_bytes = etree.tostring(wsdl_doc, xml_declaration=True, encoding='UTF-8')
        else:
            wsdl_bytes = wsdl_doc

        start_response('200 OK', [
            ('Content-Type', 'text/xml; charset=utf-8'),
            ('Content-Length', str(len(wsdl_bytes)))
        ])
        return [wsdl_bytes]

    # Pour tout le reste (POST SOAP), déléguer à Spyne
    return wsgi_app(environ, start_response)

if __name__ == '__main__':
    from wsgiref.simple_server import make_server

    port = int(os.environ.get('SOAP_PORT', 8000))
    server = make_server('0.0.0.0', port, app)

    print(f"Service SOAP demarré sur http://localhost:{port}")
    print(f"WSDL disponible sur http://localhost:{port}/?wsdl")

    server.serve_forever()
