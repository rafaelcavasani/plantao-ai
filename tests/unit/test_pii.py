"""Testes de core/security/pii.py (T011)."""

from core.security.pii import mascarar_dados, mascarar_telefone, mascarar_texto


def test_mascara_jid_do_whatsapp() -> None:
    saida = mascarar_telefone("remetente 5511999990000@s.whatsapp.net")
    assert "5511999990000" not in saida
    assert saida.endswith("0000@s.whatsapp.net")


def test_mascara_telefone_formatado() -> None:
    saida = mascarar_telefone("Ligue para +55 (11) 99999-0000 agora")
    assert "99999" not in saida
    assert "0000" in saida


def test_nao_mexe_em_numeros_curtos() -> None:
    assert mascarar_texto("São 8h às 12h, R$ 150,00") == "São 8h às 12h, R$ 150,00"


def test_mascara_email() -> None:
    assert "maria@exemplo.com" not in mascarar_texto("contato maria@exemplo.com")


def test_mascara_dict_aninhado_por_chave_e_valor() -> None:
    dados = {
        "nome": "Maria Souza",
        "evento": "mensagem",
        "extra": {"telefone": "5511999990000", "obs": "falou com 11999990000"},
        "lista": ["5511988887777", {"contato": "x"}],
    }
    saida = mascarar_dados(dados)
    assert saida["nome"] == "***"
    assert saida["evento"] == "mensagem"
    assert saida["extra"]["telefone"] == "***"
    assert "11999990000" not in saida["extra"]["obs"]
    assert "5511988887777" not in str(saida["lista"])
    assert saida["lista"][1]["contato"] == "***"


def test_valores_nao_string_passam_intactos() -> None:
    assert mascarar_dados({"n": 3, "ok": True, "x": None}) == {"n": 3, "ok": True, "x": None}
