# Mesa Posta · API (amostra de código)

API para o cerimonial de casamentos organizar **convidados, confirmação de presença (RSVP), mesas e
check-in na entrada por QR code**.

> **Duas versões do mesmo projeto:**
>
> | Repositório | O que é |
> |---|---|
> | **mesa-posta-api** (este) | **Amostra de código**: só o backend, com foco nas regras de negócio, na concorrência e nos testes. A interface é a documentação da API (`/docs`) |
> | [mesa-posta-app](https://github.com/leoesquivelcouto/mesa-posta-app) | **Produto finalizado**: o mesmo backend com telas para cerimonial, noivos, convidados (no celular) e recepção (leitor de QR pela câmera) |
>
> **Status:** v0.1, backend completo e testado. Ainda não foi usado num evento real; a validação com um
> cerimonial de Brasília onde trabalhei acontece com a versão completa.

## O problema

Trabalhei com cerimonial de casamentos. A lista de convidados vive numa planilha que circula por WhatsApp
entre cerimonial, noivos e família; a confirmação de presença é feita mensagem por mensagem; o mapa de mesas
é refeito à mão a cada mudança; e, na entrada, a recepção procura nomes numa lista impressa enquanto a fila
cresce.

## O que faz

- **Eventos com equipe e papéis:** cerimonial (tudo), noivos (convidados e mesas) e recepção (consulta e
  check-in).
- **Convidados:** cadastro, busca, filtros, paginação e **importação da planilha** (CSV do Excel ou do Google
  Planilhas).
- **Confirmação de presença por link único:** cada convidado recebe um link; ao abrir, confirma ou recusa e
  informa restrição alimentar. Há prazo para responder.
- **Mesas com capacidade garantida:** nunca há mais convidados do que lugares, mesmo com duas pessoas
  editando ao mesmo tempo.
- **Check-in por QR code:** o mesmo link do convite vira QR code; a recepção lê na entrada e vê a mesa da
  pessoa. Ler o mesmo QR duas vezes não gera duas entradas.
- **Painel do evento:** confirmados, recusados, pendentes, presentes, lugares e confirmados ainda sem mesa.

## Regras de negócio e como são garantidas

| Regra | Como | Teste |
|---|---|---|
| Mesa nunca passa da capacidade, nem com pedidos simultâneos | `SELECT ... FOR UPDATE` na linha da mesa antes de contar os ocupados; bloqueios sempre na mesma ordem (convidado, depois mesa) para não haver deadlock | `test_ultimo_lugar_disputado_ao_mesmo_tempo` prova que a segunda transação **espera** o bloqueio |
| Convidado só senta em mesa do próprio evento | **Chave estrangeira composta** `(mesa_id, evento_id)` no PostgreSQL, além da checagem na API | `test_banco_recusa_mesa_de_outro_evento_mesmo_sem_a_api` grava direto no banco e é barrado |
| Quem recusou não ocupa lugar | `CHECK` no banco; recusar (pelo link ou pelo cerimonial) libera a mesa | `test_recusar_pelo_link_libera_a_mesa` |
| Apagar uma mesa não apaga convidados | `ON DELETE SET NULL (mesa_id)` (PostgreSQL 15+): zera só a mesa, não o evento | `test_excluir_mesa_deixa_convidados_sem_mesa` |
| Link de convite impossível de adivinhar e inútil se o banco vazar | Token de 256 bits (`secrets`); o banco guarda só o **hash SHA-256**. O link aparece uma vez, ao ser gerado | `test_gerar_convites_guarda_so_o_hash`, `test_regenerar_invalida_links_antigos` |
| Um check-in por pessoa, mesmo com dois leitores ao mesmo tempo | `UPDATE ... WHERE checkin_em IS NULL RETURNING id`: o banco garante que só um pedido encontra a linha nessa condição | `test_dois_recepcionistas_ao_mesmo_tempo` (8 threads, 1 check-in) |
| Importação não deixa a lista pela metade | Tudo ou nada: com qualquer linha inválida nada é gravado, e a resposta lista cada linha a corrigir | `test_importacao_com_erro_nao_grava_nada` |
| Quem não participa do evento não descobre que ele existe | Responde 404 (não 403) para não-membros | `test_permissoes_por_papel` |

### Verificado com o servidor rodando

Com 120 convidados fictícios importados por CSV e 10 mesas, contra o servidor real (uvicorn + PostgreSQL):

- 8 pedidos **simultâneos** pelos 3 lugares de uma mesa: 3 aceitos, 5 recusados com `409 mesa_lotada`;
- o mesmo QR code lido em 5 leitores ao mesmo tempo: 1 check-in e 4 `409 checkin_repetido`;
- 120 confirmações de presença pelo link em 0,6 s;
- nenhuma linha de log com o token do convite (todas aparecem como `/convite/***`).

### Um bug que os testes pegaram

Enviar `"grupo": null` derrubava a API com erro 500: o limite de tamanho estava aplicado ao tipo
`str | None` inteiro, e o Pydantic não sabe medir `None`. A correção foi aplicar o limite só ao `str` de
dentro; o caso virou o teste `test_campos_opcionais_nulos_ou_vazios`.

## Arquitetura

```
FastAPI ── rotas/ (traduzem HTTP)  ──>  servicos.py (regras de negócio)  ──>  SQLAlchemy 2 ──> PostgreSQL
   │                                                                                 ▲
   ├── deps.py      login (JWT) e papel no evento, por injeção de dependência        │
   ├── esquemas.py  validação com Pydantic (telefone, textos, prazos com fuso)  Alembic (migrações)
   └── erros.py     formato único de erro
```

```
usuario ──< membro >── evento ──< mesa
                          │         │ (mesa_id, evento_id)
                          └──< convidado
```

### Endpoints principais

Documentação interativa completa em `/docs` (OpenAPI).

| Método | Caminho | Quem |
|---|---|---|
| `POST` | `/auth/cadastro`, `/auth/login` | qualquer pessoa |
| `POST` `GET` | `/eventos` | usuário logado |
| `PUT` `GET` | `/eventos/{id}/membros` | cerimonial |
| `GET` | `/eventos/{id}/convidados?busca=&resposta=&sem_mesa=&presente=&limite=&offset=` | equipe |
| `POST` | `/eventos/{id}/convidados/importar` | cerimonial, noivos |
| `PUT` | `/eventos/{id}/convidados/{cid}/mesa` | cerimonial, noivos |
| `POST` | `/eventos/{id}/convites?formato=csv` | cerimonial |
| `GET` `POST` | `/convite/{token}` | convidado (o link é a credencial) |
| `GET` | `/convite/{token}/qr.svg` | convidado |
| `POST` | `/eventos/{id}/checkin` | equipe |
| `GET` | `/eventos/{id}/resumo` | equipe |

Todos os erros têm o mesmo formato:

```json
{"erro": {"codigo": "mesa_lotada", "mensagem": "A mesa Mesa 3 já está com 10 de 10 lugares ocupados."}}
```

## Como rodar

### Com Docker

```bash
cp .env.example .env    # preencha SEGREDO_JWT
docker compose up --build
```

API em http://localhost:8000 e documentação em http://localhost:8000/docs. As migrações rodam ao subir.

### Sem Docker

Requer Python 3.12+ e PostgreSQL 15+.

```bash
python -m venv .venv && .venv\Scripts\activate      # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                                  # ajuste DATABASE_URL e SEGREDO_JWT
alembic upgrade head
uvicorn mesa.app:app --reload --no-access-log
```

## Testes

```bash
pytest --cov      # 57 testes, cobertura de 97% (precisa de TEST_DATABASE_URL)
ruff check .
```

Os testes rodam contra um **PostgreSQL de verdade**, com o esquema criado pelas próprias migrações (que
também são testadas na volta: `upgrade`, `downgrade`, `upgrade`). Restrições, bloqueios e concorrência não
podem ser testados com SQLite ou com mocks. O CI (GitHub Actions) roda lint, testes e cobertura mínima de
80% com PostgreSQL em contêiner, e compila a imagem Docker.

## Decisões

- **FastAPI + SQLAlchemy 2 + Alembic.** Migrações versionadas permitem mudar o banco com o sistema em uso,
  sem recriar tabelas.
- **Regras críticas no banco, não só no código.** Se um bug na API tentar gravar algo inválido, o PostgreSQL
  recusa.
- **Rotas finas, serviço com as regras.** As regras ficam em `servicos.py`, testáveis sem HTTP (o teste de
  concorrência chama o serviço direto, com duas sessões).
- **JWT curto (60 min) e senha com bcrypt.** O login leva o mesmo tempo para e-mail inexistente e senha
  errada, para não revelar quais e-mails têm conta.
- **Logs sem segredos.** O middleware mascara o token dos convites, e o uvicorn roda com `--no-access-log`
  (o log de acesso dele gravaria o link inteiro).
- **Telefone só com dígitos e DDD**, aceitando `+55`, parênteses e traços, para servir de base a links de
  WhatsApp.

## Dados pessoais (LGPD)

O sistema guarda nome, telefone e e-mail de convidados e, opcionalmente, restrição alimentar, que pode
revelar dado de saúde ou religião. Por isso:

- a página do convidado mostra só o nome dele e os dados do evento, nunca a lista;
- a recepção só consulta e faz check-in: não edita convidados nem gera links de convite;
- os links de convite não ficam no banco (só o hash).

Falta implementar a **exclusão automática dos dados após o evento** (está nos próximos passos).

## Limitações conhecidas

- Sem interface própria: aqui tudo é feito pela API (ou por `/docs`). A interface está no [mesa-posta-app](https://github.com/leoesquivelcouto/mesa-posta-app).
- Sem recuperação de senha nem convite da equipe por e-mail (a pessoa cria a conta e o cerimonial a adiciona).
- O link vale até alguém regenerar os convites; não há expiração por token individual, só o prazo do evento.
- Sem limite de requisições por IP. Adivinhar um token de 256 bits é inviável, mas o login deveria ter.

## Próximos passos

- [ ] Validar as funcionalidades com o cerimonial (o que falta, o que sobra).
- [x] Interface web: feita no [mesa-posta-app](https://github.com/leoesquivelcouto/mesa-posta-app).
- [ ] Deploy (API e PostgreSQL gerenciado) com CI/CD.
- [ ] Usar num evento real e registrar os números aqui.
- [ ] Anonimizar convidados X dias após o evento; limite de tentativas no login.
- [ ] Acompanhantes ("+1") por convite.

## Licença

MIT.

## Como foi construído

Desenvolvido com auxílio de um assistente de IA (Claude) para acelerar a implementação. As regras de negócio
vêm da minha experiência no cerimonial; as decisões e os problemas encontrados estão no histórico de commits.
