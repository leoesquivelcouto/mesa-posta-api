import threading
import time

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from mesa.db import fabrica
from mesa.erros import ErroApp
from mesa.modelos import Convidado, Mesa
from mesa.servicos import atribuir_mesa


def _sentar(client, cabecalho, evento, convidado_id, mesa_id):
    return client.put(
        f"/eventos/{evento}/convidados/{convidado_id}/mesa", json={"mesa_id": mesa_id}, headers=cabecalho
    )


def test_mesa_nao_passa_da_capacidade(client, cerimonial, evento, convidado, mesa):
    m = mesa("Mesa 1", 2)
    a, b, c = convidado("Ana"), convidado("Bruno"), convidado("Carla")
    assert _sentar(client, cerimonial, evento, a, m).status_code == 200
    assert _sentar(client, cerimonial, evento, b, m).status_code == 200
    r = _sentar(client, cerimonial, evento, c, m)
    assert r.status_code == 409
    assert r.json()["erro"]["codigo"] == "mesa_lotada"
    # Repetir a mesma atribuição não conta duas vezes.
    assert _sentar(client, cerimonial, evento, a, m).status_code == 200

    mesas = client.get(f"/eventos/{evento}/mesas", headers=cerimonial).json()
    assert mesas == [{"id": m, "nome": "Mesa 1", "capacidade": 2, "ocupados": 2}]

    # Tirar alguém da mesa abre o lugar.
    assert _sentar(client, cerimonial, evento, a, None).json()["mesa_id"] is None
    assert _sentar(client, cerimonial, evento, c, m).status_code == 200


def test_quem_recusou_nao_ocupa_lugar(client, cerimonial, evento, convidado, mesa):
    m = mesa("Mesa 1", 2)
    a = convidado("Ana")
    client.patch(f"/eventos/{evento}/convidados/{a}", json={"resposta": "recusado"}, headers=cerimonial)
    r = _sentar(client, cerimonial, evento, a, m)
    assert r.status_code == 409
    assert r.json()["erro"]["codigo"] == "convidado_recusou"


def test_mesa_de_outro_evento(client, cerimonial, evento, convidado):
    outro = client.post("/eventos", json={"nome": "Outro", "data": "2027-06-01"}, headers=cerimonial).json()[
        "id"
    ]
    m_outro = client.post(
        f"/eventos/{outro}/mesas", json={"nome": "M", "capacidade": 5}, headers=cerimonial
    ).json()["id"]
    assert _sentar(client, cerimonial, evento, convidado("Ana"), m_outro).status_code == 404


def test_banco_recusa_mesa_de_outro_evento_mesmo_sem_a_api(client, cerimonial, evento, convidado):
    """A chave estrangeira composta protege o dado mesmo que um bug na API tente gravar errado."""
    outro = client.post("/eventos", json={"nome": "Outro", "data": "2027-06-01"}, headers=cerimonial).json()[
        "id"
    ]
    m_outro = client.post(
        f"/eventos/{outro}/mesas", json={"nome": "M", "capacidade": 5}, headers=cerimonial
    ).json()["id"]
    a = convidado("Ana")
    with fabrica()() as s, pytest.raises(IntegrityError, match="convidado_mesa_mesmo_evento"):
        s.execute(text("UPDATE convidado SET mesa_id = :m WHERE id = :c"), {"m": m_outro, "c": a})
        s.commit()


def test_banco_recusa_recusado_com_mesa(client, cerimonial, evento, convidado, mesa):
    m = mesa("Mesa 1", 5)
    a = convidado("Ana")
    with fabrica()() as s, pytest.raises(IntegrityError, match="convidado_recusado_sem_mesa"):
        s.execute(
            text("UPDATE convidado SET mesa_id = :m, resposta = 'recusado' WHERE id = :c"), {"m": m, "c": a}
        )
        s.commit()


def test_reduzir_capacidade_abaixo_da_ocupacao(client, cerimonial, evento, convidado, mesa):
    m = mesa("Mesa 1", 3)
    for nome in ["Ana", "Bruno"]:
        _sentar(client, cerimonial, evento, convidado(nome), m)
    url = f"/eventos/{evento}/mesas/{m}"
    r = client.patch(url, json={"capacidade": 1}, headers=cerimonial)
    assert r.status_code == 409
    assert r.json()["erro"]["codigo"] == "capacidade_menor_que_ocupacao"
    r = client.patch(url, json={"capacidade": 2, "nome": "Mesa dos padrinhos"}, headers=cerimonial)
    assert r.json() == {"id": m, "nome": "Mesa dos padrinhos", "capacidade": 2, "ocupados": 2}


def test_nome_de_mesa_repetido(client, cerimonial, evento, mesa):
    mesa("Mesa 1", 8)
    m2 = mesa("Mesa 2", 8)
    r = client.post(f"/eventos/{evento}/mesas", json={"nome": "Mesa 1", "capacidade": 8}, headers=cerimonial)
    assert r.status_code == 409
    r = client.patch(f"/eventos/{evento}/mesas/{m2}", json={"nome": "Mesa 1"}, headers=cerimonial)
    assert r.status_code == 409


def test_excluir_mesa_deixa_convidados_sem_mesa(client, cerimonial, evento, convidado, mesa):
    m = mesa("Mesa 1", 8)
    a = convidado("Ana")
    _sentar(client, cerimonial, evento, a, m)
    assert client.delete(f"/eventos/{evento}/mesas/{m}", headers=cerimonial).status_code == 204
    ana = client.get(f"/eventos/{evento}/convidados/{a}", headers=cerimonial).json()
    assert ana["mesa_id"] is None  # o convidado continua no evento
    assert client.delete(f"/eventos/{evento}/mesas/{m}", headers=cerimonial).status_code == 404


def test_ultimo_lugar_disputado_ao_mesmo_tempo(client, evento, convidado, mesa):
    """Dois pedidos simultâneos pelo último lugar: só um pode ganhar.

    A sessão `primeira` trava a mesa e senta a Ana, sem confirmar. Enquanto isso, outra thread tenta sentar
    o Bruno na mesma mesa: ela precisa ficar esperando o bloqueio. Quando a primeira confirma, a segunda
    conta os ocupados de novo e recebe "mesa lotada". Sem o FOR UPDATE, as duas contariam 0 e a mesa
    ficaria com 2 pessoas em 1 lugar.
    """
    m = mesa("Mesa 1", 1)
    ana, bruno = convidado("Ana"), convidado("Bruno")
    resultado: dict[str, object] = {}

    def disputar():
        with fabrica()() as s:
            try:
                atribuir_mesa(s, evento, bruno, m)
                resultado["bruno"] = "sentou"
            except ErroApp as e:
                resultado["bruno"] = e.codigo

    with fabrica()() as primeira:
        primeira.scalar(select(Mesa).where(Mesa.id == m).with_for_update())
        primeira.get(Convidado, ana).mesa_id = m
        primeira.flush()

        outra = threading.Thread(target=disputar)
        outra.start()
        time.sleep(0.5)
        assert outra.is_alive(), "a segunda transação deveria estar esperando o bloqueio da mesa"
        primeira.commit()

    outra.join(timeout=5)
    assert resultado == {"bruno": "mesa_lotada"}
    with fabrica()() as s:
        assert s.scalar(select(Convidado.mesa_id).where(Convidado.id == bruno)) is None
