"""Local, interactive Telegram login for creating a protected StringSession."""
import asyncio
from getpass import getpass
from telethon import TelegramClient
from telethon.sessions import StringSession

async def main():
    api_id=int(input("API ID (my.telegram.org): "))
    api_hash=getpass("API Hash: ").strip()
    phone=input("Telefone internacional (por exemplo +351...): ").strip()
    async with TelegramClient(StringSession(),api_id,api_hash) as client:
        await client.start(phone=phone)
        print("\nGuarda o valor seguinte APENAS em GitHub Settings > Secrets > TG_SESSION.")
        print("Nunca coloques esta sessão em código, issues, prints ou conversas.")
        print(client.session.save())
        print("\nIdentifica o canal AsianOdds pelo nome exato ou ID:")
        async for d in client.iter_dialogs():
            if d.is_channel:
                print("Canal:",d.id,d.name)

if __name__=="__main__":
    asyncio.run(main())
