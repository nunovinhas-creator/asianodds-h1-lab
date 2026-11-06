"""Carrega uma sessão Telethon sem expor o seu conteúdo nos logs.

A sessão é uma credencial de acesso total à conta; nunca a imprimir.
"""
from contextlib import asynccontextmanager

import asyncio
import binascii
import os
import struct
import sys


SETUP_TIMEOUT_SECONDS = 30
READ_TIMEOUT_SECONDS = 300
DISCONNECT_TIMEOUT_SECONDS = 5


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


@asynccontextmanager
async def authorized_channel():
    """Open the configured channel without entering Telethon's interactive start()."""
    from telethon import TelegramClient, errors
    from telethon.tl.functions.updates import GetStateRequest
    from .telegram_transport import ConnectionTcpFullWithShortErrors

    try:
        api_id = int(os.environ["TG_API_ID"])
    except ValueError:
        raise TelegramSessionError("TELEGRAM_API_CONFIG_INVALID") from None

    client = TelegramClient(load_telegram_session(), api_id, os.environ["TG_API_HASH"],
                            connection=ConnectionTcpFullWithShortErrors,
                            receive_updates=False, flood_sleep_threshold=0,
                            timeout=10, connection_retries=1, request_retries=1,
                            retry_delay=1, auto_reconnect=False, raise_last_call_error=True)
    stage = "CONNECT"
    try:
        print("TELEGRAM_PHASE_START CONNECT", flush=True)
        await asyncio.wait_for(client.connect(), SETUP_TIMEOUT_SECONDS)
        print(f"TELEGRAM_PHASE_OK {stage}", flush=True)
        stage = "AUTHORIZE"
        print(f"TELEGRAM_PHASE_START {stage}", flush=True)
        # is_user_authorized() maps every RPCError to False. Use its underlying
        # request directly to distinguish rejected sessions from temporary errors.
        await asyncio.wait_for(client(GetStateRequest()), SETUP_TIMEOUT_SECONDS)
        print(f"TELEGRAM_PHASE_OK {stage}", flush=True)
        stage = "CHANNEL_LOOKUP"
        print(f"TELEGRAM_PHASE_START {stage}", flush=True)
        async with asyncio.timeout(SETUP_TIMEOUT_SECONDS):
            wanted = os.environ["TG_CHANNEL"].strip()
            if wanted.startswith("@"):
                try:
                    entity = await client.get_entity(wanted)
                except ValueError:
                    raise TelegramSessionError("TELEGRAM_CHANNEL_UNAVAILABLE CHANNEL_LOOKUP") from None
            else:
                dialogs = [dialog async for dialog in client.iter_dialogs()]
                matches = [d.entity for d in dialogs if str(d.id) == wanted or d.name == wanted]
                if len(matches) != 1:
                    raise TelegramSessionError("TELEGRAM_CHANNEL_UNAVAILABLE CHANNEL_LOOKUP")
                entity = matches[0]
        print(f"TELEGRAM_PHASE_OK {stage}", flush=True)
        stage = "CHANNEL_READ"
        print(f"TELEGRAM_PHASE_START {stage}", flush=True)
        async with asyncio.timeout(READ_TIMEOUT_SECONDS):
            yield client, entity
        print("TELEGRAM_PHASE_OK CHANNEL_READ", flush=True)
    except TimeoutError:
        raise TelegramSessionError(f"TELEGRAM_TIMEOUT {stage}") from None
    except (errors.SessionRevokedError, errors.SessionExpiredError,
            errors.AuthKeyDuplicatedError, errors.AuthKeyUnregisteredError) as exc:
        raise TelegramSessionError(f"TELEGRAM_SESSION_REJECTED {type(exc).__name__}") from None
    except errors.AuthKeyNotFound:
        # Telethon documents that this may be temporary.
        raise TelegramSessionError("TELEGRAM_AUTH_KEY_NOT_FOUND") from None
    except errors.UnauthorizedError:
        raise TelegramSessionError(f"TELEGRAM_SESSION_UNAUTHORIZED {stage}") from None
    except (errors.ChannelPrivateError, errors.ChannelInvalidError,
            errors.UsernameInvalidError, errors.UsernameNotOccupiedError):
        raise TelegramSessionError(f"TELEGRAM_CHANNEL_UNAVAILABLE {stage}") from None
    except (OSError, errors.ServerError, errors.TimedOutError, errors.FloodWaitError):
        raise TelegramSessionError(f"TELEGRAM_TEMPORARY_FAILURE {stage}") from None
    except errors.RPCError as exc:
        raise TelegramSessionError(f"TELEGRAM_RPC_FAILURE {stage} {type(exc).__name__}") from None
    finally:
        # Cleanup must never replace the original rejection/transport diagnosis.
        primary_error = sys.exc_info()[0] is not None
        print("TELEGRAM_PHASE_START DISCONNECT", flush=True)
        try:
            await asyncio.wait_for(client.disconnect(), DISCONNECT_TIMEOUT_SECONDS)
        except Exception as exc:
            reason = ("TELEGRAM_TIMEOUT DISCONNECT" if isinstance(exc, TimeoutError)
                      else "TELEGRAM_DISCONNECT_FAILED")
            print(reason, flush=True)
            if not primary_error:
                raise TelegramSessionError(reason) from None
        else:
            # Telethon also stores the primary transport failure in its public
            # disconnected future. Retrieve that completed failure so asyncio
            # does not emit an unrelated "Future exception was never retrieved".
            disconnected = client.disconnected
            if isinstance(disconnected, asyncio.Future) and disconnected.done() and not disconnected.cancelled():
                failure = disconnected.exception()
                if failure is not None and not primary_error:
                    raise TelegramSessionError("TELEGRAM_DISCONNECT_FAILED") from None
            print("TELEGRAM_PHASE_OK DISCONNECT", flush=True)
