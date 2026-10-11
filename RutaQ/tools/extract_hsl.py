"""Extract a reproducible four-departure historical planning scenario."""
import csv, hashlib, json, sys
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

if len(sys.argv) != 2:
    raise SystemExit('Usage: python tools/extract_hsl.py /path/to/hsl.zip')
source = Path(sys.argv[1])
out = Path(__file__).resolve().parents[1] / 'data'
expected = '6392a74d85e1775637f9c96a3db93d823e72fcfc277cf20d7e906244fa866316'
if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
    raise SystemExit('Snapshot differs from the reviewed feed; adapt selection and calendar checks before regenerating.')
with ZipFile(source) as z:
    def rows(name):
        return csv.DictReader(TextIOWrapper(z.open(name), encoding='utf-8-sig'))
    calendar = {r['service_id']: r for r in rows('calendar.txt')}
    stops = {r['stop_id']: r for r in rows('stops.txt')}
    trips = {r['trip_id']: r for r in rows('trips.txt')
             if r['route_id'] == '1001' and r['service_id'] == '1001_20261009_20261030_Ke'
             and r['direction_id'] == '0' and r['trip_id'].rsplit('_', 1)[-1] >= '0800'}
    selected = sorted(trips)[:4]
    records = {i: [] for i in selected}
    for n, r in enumerate(rows('stop_times.txt')):
        if r['trip_id'] in records:
            records[r['trip_id']].append(r)
        if all(len(rs) >= 20 for rs in records.values()):
            break
    def seconds(value):
        h, m, s = map(int, value.split(':'))
        return 3600*h+60*m+s
    origin, destination = '1050417', '1020444'
    options, evidence = [], []
    for tid in selected:
        trip = trips[tid]
        assert calendar[trip['service_id']]['wednesday'] == '1'
        assert calendar[trip['service_id']]['start_date'] <= '20261014' <= calendar[trip['service_id']]['end_date']
        start = next(r for r in records[tid] if r['stop_id'] == origin)
        end = next(r for r in records[tid] if r['stop_id'] == destination)
        assert start['pickup_type'] != '1' and end['drop_off_type'] != '1'
        elapsed = seconds(end['arrival_time'])-seconds('08:00:00')
        assert elapsed % 60 == 0 and 0 <= elapsed // 60 <= 63
        codes = [trip['wheelchair_accessible'], stops[origin]['wheelchair_boarding'], stops[destination]['wheelchair_boarding']]
        options.append(dict(option_id=tid, travel_time_minutes=elapsed//60,
                            available_seats=None, wheelchair_accessible=all(v == '1' for v in codes)))
        evidence.append(dict(trip=trip, calendar=calendar[trip['service_id']], origin_stop=stops[origin],
                             destination_stop=stops[destination], boarding=start, alighting=end))
    feed_info = next(rows('feed_info.txt'))
    exceptions = [r for r in rows('calendar_dates.txt') if r['date'] == '20261014' and r['service_id'] == '1001_20261009_20261030_Ke']
    assert not any(r['exception_type']=='2' for r in exceptions)
metadata = dict(publisher='Helsinki Region Transport (HSL)', source_url='https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip',
                source_page='https://www.hsl.fi/en/opendata', license='CC BY 4.0', attribution='© HSL 2026',
                downloaded_at_date='2026-10-11', source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                feed_info=feed_info, selection_rule='First four route 1001 direction 0 departures at or after 08:00 for service 1001_20261009_20261030_Ke; no filtering by feasibility.',
                planning_date='2026-10-14', reference_time='08:00:00', origin_stop_id=origin,
                destination_stop_id=destination, origin_name=stops[origin]['stop_name'], destination_name=stops[destination]['stop_name'],
                elapsed_definition='Minutes from 08:00 to scheduled arrival, including waiting.',
                capacity_status='Not provided by GTFS; disabled rather than fabricated.',
                accessibility_rule='Confirmed only when trip and both boarding/alighting stops have code 1; unknown codes are not confirmation.',
                calendar_exceptions=exceptions)
(out/'public_departures.json').write_text(json.dumps(dict(data_kind='public_gtfs_extract', metadata=metadata,
    options=options, constraints=dict(max_travel_time_minutes=20, min_available_seats=None, requires_wheelchair_access=True)), indent=2, ensure_ascii=False)+'\n')
(out/'source_rows.json').write_text(json.dumps(dict(metadata=metadata, rows=evidence), indent=2, ensure_ascii=False)+'\n')
print([(o['option_id'], o['travel_time_minutes'], o['wheelchair_accessible']) for o in options])
