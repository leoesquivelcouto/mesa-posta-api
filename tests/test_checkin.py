import threading

from mesa.db import fabrica
from mesa.erros import ErroApp
from mesa.servicos import extrair_token, fazer_checkin


def _preparar(client, cerimonial, evento, convidado, mesa, *, confirmar=True, sentar=True):
    cid = convidado("Ana")
    if confirmar:
        client.patch(
            f"/eventos/{evento}/convidados/{cid}", json={"resposta": "confirmado"}, headers=cerimonial
        )
    if sentar:
        m = mesa("Mesa 7", 8)
        client.put(f"/eventos/{evento}/convidados/{cid}/mesa", json={"mesa_id": m}, headers=cerimonial)
    link = client.post(f"/eventos/{evento}/convites", headers=cerimonial).json()[0]["link"]
    return cid, link


def test_checkin_pelo_qr_code(client, evento, equipe, convidado, mesa):
    _, link = _preparar(client, equipe["cerimonial"], evento, convidado, mesa)
    r = client.post(f"/eventos/{evento}/checkin", json={"codigo": link}, headers=equipe["recepcao"])
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["convidado"]["nome"] == "Ana"
    assert corpo["convidado"]["checkin_em"] is not None
    assert (corpo["mesa"], corpo["aviso"]) == ("Mesa 7", None)


def test_mesmo_qr_duas_vezes(client, evento, equipe, convidado, mesa):
    _, link = _preparar(client, equipe["cerimonial"], evento, convidado, mesa)
    client.post(f"/eventos/{evento}/checkin", json={"codigo": link}, headers=equipe["recepcao"])
    r = client.post(f"/eventos/{evento}/checkin", json={"codigo": link + "/"}, headers=equipe["recepcao"])
    assert r.status_code == 409
    assert r.json()["erro"]["codigo"] == "checkin_repetido"
    assert "checkin_em" in r.json()["erro"]["detalhes"]


def test_avisos_na_entrada(client, cerimonial, evento, convidado, mesa):
    _, link = _preparar(client, cerimonial, evento, convidado, mesa, confirmar=False, sentar=False)
    r = client.post(f"/eventos/{evento}/checkin", json={"codigo": extrair_token(link)}, headers=cerimonial)
    assert "sem confirmação" in r.json()["aviso"]


def test_confirmado_sem_mesa(client, cerimonial, evento, convidado, mesa):
    _, link = _preparar(client, cerimonial, evento, convidado, mesa, sentar=False)
    r = client.post(f"/eventos/{evento}/checkin", json={"codigo": link}, headers=cerimonial)
    assert r.json()["aviso"] == "Convidado confirmado, mas ainda sem mesa."


def test_qr_de_outro_evento_nao_entra(client, cerimonial, evento, convidado, mesa):
    _, link = _preparar(client, cerimonial, evento, convidado, mesa)
    outro = client.post("/eventos", json={"nome": "Outro", "data": "2027-06-01"}, headers=cerimonial).json()[
        "id"
    ]
    r = client.post(f"/eventos/{outro}/checkin", json={"codigo": link}, headers=cerimonial)
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "convite_invalido"


def test_checkin_manual_e_filtro_de_presentes(client, evento, equipe, convidado, mesa):
    cid, _ = _preparar(client, equipe["cerimonial"], evento, convidado, mesa)
    url = f"/eventos/{evento}/convidados"
    assert client.post(f"{url}/{cid}/checkin", headers=equipe["recepcao"]).status_code == 200
    assert client.post(f"{url}/{cid}/checkin", headers=equipe["recepcao"]).status_code == 409
    presentes = client.get(url, params={"presente": True}, headers=equipe["recepcao"]).json()
    assert [c["nome"] for c in presentes["itens"]] == ["Ana"]
    assert client.post(f"{url}/999/checkin", headers=equipe["recepcao"]).status_code == 404


def test_dois_recepcionistas_ao_mesmo_tempo(client, cerimonial, evento, convidado, mesa):
    """O mesmo QR lido em duas entradas ao mesmo tempo gera exatamente um check-in."""
    cid, _ = _preparar(client, cerimonial, evento, convidado, mesa)
    barreira = threading.Barrier(8)
    resultados: list[str] = []

    def ler():
        with fabrica()() as s:
            barreira.wait()
            try:
                fazer_checkin(s, evento, cid)
                resultados.append("ok")
            except ErroApp as e:
                resultados.append(e.codigo)

    threads = [threading.Thread(target=ler) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert sorted(resultados) == ["checkin_repetido"] * 7 + ["ok"]
