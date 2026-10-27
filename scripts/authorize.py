"""Autenticação local e interativa de uma conta Telegram via Telethon.

Não guarda credenciais nem sessões no disco/repositório.
"""
import asyncio
from getpass import getpass

from telethon import TelegramClient
from telethon.errors import ApiIdInvalidError
from telethon.sessions import StringSession


async def main():
    print("Autenticação de conta Telegram — AsianOdds H1 Lab")
    try:
        api_id = int(input("API ID (número indicado em my.telegram.org): ").strip())
    except ValueError:
        print("API ID inválido: introduz apenas o número, sem aspas.")
        return

    api_hash = getpass("API Hash (valor completo, sem espaços): ").strip()
    phone = input("Telefone com indicativo internacional (ex.: +351...): ").strip().replace(" ", "")

    if not phone.startswith("+") or not phone[1:].isdigit():
        print("Telefone inválido. Volta a executar e escreve + seguido do indicativo e número.")
        return

    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.connect()
        # A sessão já está ligada: não usar 'async with', pois esse contexto
        # chama .start() automaticamente e pede o telefone uma segunda vez.
        await client.start(phone=phone)

        print("\nCopia o valor seguinte DIRETAMENTE para o secret TG_SESSION no GitHub.")
        print("Este valor é uma credencial: nunca o envies por chat, screenshot ou commit.")
        print(client.session.save())

        print("\nCanais subscritos (para confirmar o nome/ID do canal AsianOdds):")
        async for dialog in client.iter_dialogs():
            if dialog.is_channel:
                print(" ", dialog.id, dialog.name)
    except ApiIdInvalidError:
        print("\nAPI ID / API Hash rejeitados pelo Telegram.")
        print("Confirma os dois valores na MESMA aplicação em my.telegram.org.")
        print("O API ID é numérico; o API Hash é uma sequência de caracteres.")
        print("Não partilhes nenhum deles para diagnóstico.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
