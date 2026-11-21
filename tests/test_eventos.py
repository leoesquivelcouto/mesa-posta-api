import pytest


def test_quem_cria_vira_cerimonial_e_so_ve_os_proprios_eventos(client, cerimonial, evento, nova_conta):
    r = client.get("/eventos", headers=cerimonial)
    assert [(e["id"], e["papel"]) for e in r.json()] == [(evento, "cerimonial")]

    outra = nova_conta("outra@cerimonial.com")
    assert client.get("/eventos", headers=outra).json() == []
    # Quem não participa recebe 404, não 403: não descobre que o evento existe.
    r = client.get(f"/eventos/{evento}", headers=outra)
    assert r.status_code == 404


def test_prazo_precisa_de_fuso_horario(client, cerimonial):
    dados = {"nome": "Festa", "data": "2027-01-10", "prazo_rsvp": "2027-01-01T23:59:00"}
    assert client.post("/eventos", json=dados, headers=cerimonial).status_code == 422
    dados["prazo_rsvp"] = "2027-01-01T23:59:00-03:00"
    assert client.post("/eventos", json=dados, headers=cerimonial).status_code == 201


@pytest.mark.parametrize(
    ("papel", "metodo", "caminho", "esperado"),
    [
        ("noivos", "post", "/mesas", 201),
        ("recepcao", "post", "/mesas", 403),
        ("recepcao", "get", "/convidados", 200),
        ("recepcao", "post", "/convidados", 403),
        ("noivos", "post", "/convites", 403),
        ("noivos", "get", "/membros", 403),
        ("noivos", "patch", "", 403),
        ("recepcao", "get", "/resumo", 200),
        ("estranho", "get", "/convidados", 404),
    ],
)
def test_permissoes_por_papel(client, evento, equipe, papel, metodo, caminho, esperado):
    corpo = {"nome": "Mesa 1", "capacidade": 8} if caminho == "/mesas" else {"nome": "Fulano"}
    kwargs = {"json": corpo} if metodo in ("post", "patch") and caminho != "/convites" else {}
    r = getattr(client, metodo)(f"/eventos/{evento}{caminho}", headers=equipe[papel], **kwargs)
    assert r.status_code == esperado, r.text


def test_equipe_e_ultimo_cerimonial(client, evento, equipe):
    c = equipe["cerimonial"]
    papeis = {m["email"]: m["papel"] for m in client.get(f"/eventos/{evento}/membros", headers=c).json()}
    assert papeis == {
        "ana@cerimonial.com": "cerimonial",
        "bia@noivos.com": "noivos",
        "rui@recepcao.com": "recepcao",
    }

    # Não dá para o evento ficar sem cerimonial.
    r = client.put(
        f"/eventos/{evento}/membros", json={"email": "ana@cerimonial.com", "papel": "noivos"}, headers=c
    )
    assert r.status_code == 409
    assert client.delete(f"/eventos/{evento}/membros/1", headers=c).status_code == 409

    # Com outro cerimonial, pode.
    client.put(
        f"/eventos/{evento}/membros", json={"email": "bia@noivos.com", "papel": "cerimonial"}, headers=c
    )
    assert client.delete(f"/eventos/{evento}/membros/1", headers=c).status_code == 204
    assert client.get(f"/eventos/{evento}", headers=c).status_code == 404


def test_membro_precisa_ter_conta(client, cerimonial, evento):
    r = client.put(
        f"/eventos/{evento}/membros", json={"email": "sem@conta.com", "papel": "noivos"}, headers=cerimonial
    )
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "usuario_nao_encontrado"


def test_atualizar_e_excluir_evento(client, cerimonial, evento, convidado):
    convidado("Fulano")
    r = client.patch(f"/eventos/{evento}", json={"local": "Salão Azul"}, headers=cerimonial)
    assert r.json()["local"] == "Salão Azul"
    assert r.json()["nome"] == "Casamento de Bia e Caio"
    assert client.patch(f"/eventos/{evento}", json={"nome": None}, headers=cerimonial).status_code == 422

    assert client.delete(f"/eventos/{evento}", headers=cerimonial).status_code == 204
    assert client.get("/eventos", headers=cerimonial).json() == []


def test_resumo(client, cerimonial, evento, convidado, mesa):
    m = mesa("Mesa 1", 4)
    mesa("Mesa 2", 6)
    a, b, _ = convidado("Ana"), convidado("Bruno"), convidado("Carla")
    url = f"/eventos/{evento}/convidados"
    client.patch(f"{url}/{a}", json={"resposta": "confirmado"}, headers=cerimonial)
    client.patch(f"{url}/{b}", json={"resposta": "recusado"}, headers=cerimonial)
    client.put(f"{url}/{a}/mesa", json={"mesa_id": m}, headers=cerimonial)
    client.post(f"{url}/{a}/checkin", headers=cerimonial)

    r = client.get(f"/eventos/{evento}/resumo", headers=cerimonial).json()
    assert r == {
        "convidados": 3,
        "confirmados": 1,
        "recusados": 1,
        "pendentes": 1,
        "presentes": 1,
        "lugares": 10,
        "sentados": 1,
        "confirmados_sem_mesa": 0,
    }
