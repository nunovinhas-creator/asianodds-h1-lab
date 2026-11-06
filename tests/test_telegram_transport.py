"""Replay the observed four-byte -404, with no real session or network."""
import asyncio
from collections import defaultdict
import logging
import struct
from types import SimpleNamespace
import unittest

from telethon import errors
from telethon.crypto import AuthKey
from telethon.network.connection.tcpfull import FullPacketCodec
from telethon.network.mtprotosender import MTProtoSender
from telethon.tl.functions import PingRequest

from h1lab.telegram_transport import ShortErrorFullPacketCodec


class Framing(unittest.IsolatedAsyncioTestCase):
    def codec(self, cls=ShortErrorFullPacketCodec):
        return cls(SimpleNamespace())

    async def test_observed_short_error_stalls_upstream_but_fixed_reader_returns_without_eof(self):
        reader = asyncio.StreamReader()
        error = struct.pack("<i", -404)
        reader.feed_data(error)
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(self.codec(FullPacketCodec).read_packet(reader), 0.02)
        self.assertEqual(await asyncio.wait_for(self.codec().read_packet(reader), 0.1), error)
        self.assertFalse(reader.at_eof())

    async def test_normal_packets_keep_payload_and_crc_validation(self):
        for payload in (b"data", b"x" * 512):
            packet = self.codec().encode_packet(payload)
            reader = asyncio.StreamReader()
            reader.feed_data(packet)
            self.assertEqual(await self.codec().read_packet(reader), payload)
            corrupted = bytearray(packet)
            corrupted[-1] ^= 1
            reader.feed_data(corrupted)
            with self.assertRaises(errors.InvalidChecksumError):
                await self.codec().read_packet(reader)

    async def test_fragmented_positive_header_still_waits_for_complete_packet(self):
        payload = b"data"
        packet = self.codec().encode_packet(payload)
        reader = asyncio.StreamReader()
        reader.feed_data(packet[:4])
        pending = asyncio.create_task(self.codec().read_packet(reader))
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        reader.feed_data(packet[4:])
        self.assertEqual(await asyncio.wait_for(pending, 0.1), payload)

    async def test_existing_three_word_flood_error_is_unchanged(self):
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack("<iii", -429, -429, -429))
        with self.assertRaises(errors.InvalidBufferError) as caught:
            await self.codec().read_packet(reader)
        self.assertEqual(caught.exception.code, 429)

    async def test_partial_eof_behavior_is_unchanged(self):
        for data in (b"", b"xx", b"xxxxxx"):
            reader = asyncio.StreamReader()
            reader.feed_data(data)
            reader.feed_eof()
            if data:
                self.assertEqual(await self.codec().read_packet(reader), data)
            else:
                with self.assertRaises(asyncio.IncompleteReadError):
                    await self.codec().read_packet(reader)

    async def test_real_sender_maps_short_reply_to_auth_key_not_found_without_key_generation(self):
        reader = asyncio.StreamReader()
        codec = self.codec()
        transmitted = asyncio.Event()
        class Connection:
            _connected = False
            async def connect(self, **kwargs):
                self._connected = True
            async def disconnect(self):
                self._connected = False
            async def send(self, data):
                transmitted.set()
            async def recv(self):
                return await codec.read_packet(reader)
        logger = logging.Logger("synthetic")
        logger.addHandler(logging.NullHandler())
        key = AuthKey(b"synthetic-key".ljust(256, b"x"))
        sender = MTProtoSender(key, loggers=defaultdict(lambda: logger), retries=1, auto_reconnect=False)
        async def forbidden(*args):
            self.fail("must never generate a replacement key")
        sender._try_gen_auth_key = forbidden
        try:
            await sender.connect(Connection())
            future = sender.send(PingRequest(1))
            await asyncio.wait_for(transmitted.wait(), 0.5)
            reader.feed_data(struct.pack("<i", -404))
            with self.assertRaises(errors.AuthKeyNotFound):
                await asyncio.wait_for(future, 0.5)
            self.assertIs(sender.auth_key, key)
            # Consume the sender's matching disconnect failure as well.
            with self.assertRaises(errors.AuthKeyNotFound):
                await sender.disconnected
        finally:
            await sender.disconnect()


if __name__ == "__main__":
    unittest.main()
