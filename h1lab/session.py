"""Carrega uma sessão Telethon sem expor o seu conteúdo nos logs.

A sessão é uma credencial de acesso total à conta; nunca a imprimir.
"""
import binascii
import os
import struct


class TelegramSessionError(RuntimeError):
    """Erro seguro para apresentar nos logs de CI."""


def load_telegram_session():
    from telethon.sessions import StringSession

    raw = os.environ.get("TG_SESSION", "")
    # Cópias do GitHub podem incluir espaços e quebras de linha.
    value = "".join(raw.split())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]

    if not value or not value.startswith("1"):
        raise TelegramSessionError(
            "SETUP_REQUIRED: TG_SESSION não é uma StringSession Telethon "
            "(falta o prefixo de versão). Copia apenas o valor completo "
            "gerado por scripts/authorize.py para o GitHub Secret TG_SESSION."
        )
    try:
        return StringSession(value)
    except (ValueError, binascii.Error, struct.error) as exc:
        raise TelegramSessionError(
            "SETUP_REQUIRED: TG_SESSION está incompleta ou mal copiada. "
            "Substitui o Secret pela nova sessão completa; não a partilhes "
            "no chat nem nos logs."
        ) from None
