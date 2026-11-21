def test_criar_normaliza_nome_e_telefone(client, cerimonial, evento):
    r = client.post(
        f"/eventos/{evento}/convidados",
        json={
            "nome": "  Maria   da Silva ",
            "telefone": "+55 (61) 99876-5432",
            "grupo": " Família da noiva ",
        },
        headers=cerimonial,
    )
    assert r.status_code == 201
    c = r.json()
    assert (c["nome"], c["telefone"], c["grupo"]) == ("Maria da Silva", "61998765432", "Família da noiva")
    assert c["resposta"] == "pendente"
    assert c["tem_convite"] is False


def test_campos_opcionais_nulos_ou_vazios(client, cerimonial, evento):
    corpo = {"nome": "João", "telefone": None, "email": None, "grupo": None}
    r = client.post(f"/eventos/{evento}/convidados", json=corpo, headers=cerimonial)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = client.patch(
        f"/eventos/{evento}/convidados/{cid}",
        json={"grupo": "   ", "restricao_alimentar": None},
        headers=cerimonial,
    )
    assert r.status_code == 200, r.text
    assert r.json()["grupo"] is None
    r = client.post(
        f"/eventos/{evento}/convidados", json={"nome": "João", "grupo": "x" * 81}, headers=cerimonial
    )
    assert r.status_code == 422


def test_telefone_invalido(client, cerimonial, evento):
    r = client.post(
        f"/eventos/{evento}/convidados", json={"nome": "João", "telefone": "9999"}, headers=cerimonial
    )
    assert r.status_code == 422
    assert r.json()["erro"]["detalhes"][0]["campo"] == "telefone"


def test_listagem_com_filtros_e_paginacao(client, cerimonial, evento, convidado, mesa):
    for nome in ["Carlos", "Ana", "Bruna", "Anderson", "100% Ana_Paula"]:
        convidado(nome)
    url = f"/eventos/{evento}/convidados"

    r = client.get(url, params={"limite": 2}, headers=cerimonial).json()
    assert [c["nome"] for c in r["itens"]] == ["100% Ana_Paula", "Ana"]
    assert r["total"] == 5
    r = client.get(url, params={"limite": 2, "offset": 4}, headers=cerimonial).json()
    assert [c["nome"] for c in r["itens"]] == ["Carlos"]

    nomes = lambda **p: [c["nome"] for c in client.get(url, params=p, headers=cerimonial).json()["itens"]]  # noqa: E731
    assert nomes(busca="an") == ["100% Ana_Paula", "Ana", "Anderson"]
    assert nomes(busca="%") == ["100% Ana_Paula"]  # o % é texto, não curinga
    assert nomes(busca="a_p") == ["100% Ana_Paula"]

    ana = client.get(url, params={"busca": "Ana"}, headers=cerimonial).json()["itens"][1]["id"]
    m = mesa("Mesa 1", 2)
    client.patch(f"{url}/{ana}", json={"resposta": "confirmado"}, headers=cerimonial)
    client.put(f"{url}/{ana}/mesa", json={"mesa_id": m}, headers=cerimonial)
    assert nomes(resposta="confirmado") == ["Ana"]
    assert nomes(mesa_id=m) == ["Ana"]
    assert len(nomes(sem_mesa=True)) == 4
    assert nomes(presente=True) == []
    assert client.get(url, params={"limite": 500}, headers=cerimonial).status_code == 422


def test_atualizar_resposta_pelo_cerimonial(client, cerimonial, evento, convidado, mesa):
    cid = convidado("Ana")
    url = f"/eventos/{evento}/convidados/{cid}"
    m = mesa("Mesa 1", 2)
    r = client.patch(
        url, json={"resposta": "confirmado", "restricao_alimentar": "vegana"}, headers=cerimonial
    )
    assert r.json()["resposta"] == "confirmado"
    assert r.json()["respondido_em"] is not None
    client.put(f"{url}/mesa", json={"mesa_id": m}, headers=cerimonial)

    # Recusar libera o lugar.
    r = client.patch(url, json={"resposta": "recusado"}, headers=cerimonial)
    assert r.json()["mesa_id"] is None
    assert client.patch(url, json={"nome": None}, headers=cerimonial).status_code == 422
    assert client.patch(url, json={"resposta": None}, headers=cerimonial).status_code == 422


def test_convidado_de_outro_evento_nao_aparece(client, cerimonial, evento, convidado):
    cid = convidado("Ana")
    outro = client.post("/eventos", json={"nome": "Outro", "data": "2027-06-01"}, headers=cerimonial).json()[
        "id"
    ]
    assert client.get(f"/eventos/{outro}/convidados/{cid}", headers=cerimonial).status_code == 404
    assert client.delete(f"/eventos/{outro}/convidados/{cid}", headers=cerimonial).status_code == 404
    assert client.delete(f"/eventos/{evento}/convidados/{cid}", headers=cerimonial).status_code == 204


# --- importação ---------------------------------------------------------------------------------


def _importar(client, cabecalho, evento, conteudo: bytes):
    return client.post(
        f"/eventos/{evento}/convidados/importar",
        files={"arquivo": ("lista.csv", conteudo, "text/csv")},
        headers=cabecalho,
    )


def test_importar_csv_do_excel(client, cerimonial, evento, convidado):
    convidado("Tia Rosa", telefone="61988887777")
    # Excel no Windows: ponto e vírgula, cp1252, nomes de coluna variados, linha em branco.
    planilha = (
        "Nome;Celular;E-mail;Família\n"
        "João Pereira;(61) 99123-4567;joao@email.com;Noivo\n"
        "\n"
        "Tia Rosa;61 98888-7777;;Noiva\n"
        "Lúcia;;;\n"
        "Lúcia;;;\n"
    ).encode("cp1252")
    r = _importar(client, cerimonial, evento, planilha)
    assert r.status_code == 200, r.text
    assert r.json() == {"importados": 2, "ignorados": ["linha 4: Tia Rosa", "linha 6: Lúcia"]}

    lista = client.get(f"/eventos/{evento}/convidados", headers=cerimonial).json()["itens"]
    joao = next(c for c in lista if c["nome"] == "João Pereira")
    assert (joao["telefone"], joao["email"], joao["grupo"]) == ("61991234567", "joao@email.com", "Noivo")


def test_importacao_com_erro_nao_grava_nada(client, cerimonial, evento):
    planilha = "nome,telefone\nAna,61999998888\nB,123\n,\nCarlos,\n".encode("utf-8-sig")
    r = _importar(client, cerimonial, evento, planilha)
    assert r.status_code == 422
    erro = r.json()["erro"]
    assert erro["codigo"] == "planilha_com_erros"
    assert [d["linha"] for d in erro["detalhes"]] == [3]
    assert len(erro["detalhes"][0]["erros"]) == 2  # nome curto e telefone inválido
    assert client.get(f"/eventos/{evento}/convidados", headers=cerimonial).json()["total"] == 0


def test_importacao_sem_coluna_nome(client, cerimonial, evento):
    r = _importar(client, cerimonial, evento, b"convidado;telefone\nAna;61999998888\n")
    assert r.status_code == 422
    assert r.json()["erro"]["codigo"] == "planilha_invalida"


def test_importacao_grande_demais(client, cerimonial, evento):
    assert _importar(client, cerimonial, evento, b"nome\n" + b"x" * 1_000_001).status_code == 413
