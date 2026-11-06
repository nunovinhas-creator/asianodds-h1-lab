"""Keep TCP Full framing while recognizing Telegram's four-byte -404 reply.

Telethon 1.45.0 waits for eight header bytes before checking errors. A server
which returns only -404 and keeps TCP open therefore looks like an RPC timeout.
Return that existing transport error to Telethon's normal MTProto decoder, which
maps it to AuthKeyNotFound. Never replace or regenerate an authentication key.
"""
import asyncio
import struct

from telethon.network.connection.tcpfull import ConnectionTcpFull, FullPacketCodec


class _PrefixedReader:
    def __init__(self, reader, prefix):
        self.reader = reader
        self.prefix = prefix

    async def readexactly(self, count):
        prefix, self.prefix = self.prefix[:count], self.prefix[count:]
        if len(prefix) == count:
            return prefix
        try:
            return prefix + await self.reader.readexactly(count - len(prefix))
        except asyncio.IncompleteReadError as exc:
            raise asyncio.IncompleteReadError(prefix + exc.partial, count) from None


class ShortErrorFullPacketCodec(FullPacketCodec):
    async def read_packet(self, reader):
        try:
            prefix = await reader.readexactly(4)
        except asyncio.IncompleteReadError as exc:
            if exc.partial:
                return exc.partial
            raise
        if struct.unpack("<i", prefix)[0] == -404:
            return prefix
        # Preserve the pinned library's length/sequence/CRC and flood handling.
        return await super().read_packet(_PrefixedReader(reader, prefix))


class ConnectionTcpFullWithShortErrors(ConnectionTcpFull):
    packet_codec = ShortErrorFullPacketCodec
