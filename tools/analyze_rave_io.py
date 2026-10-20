"""Compare stock-8088 PSG/PIT port timestamps with the frozen RWS1 schedule.

The trace is read only after the bounded native run has completed. A frame is
matched by its entire consecutive PSG byte sequence; unrelated startup and
cleanup mutes are reported separately, never silently discarded.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAVE = ROOT
NATIVE = ROOT / "build/native-trace"
RECORD = struct.Struct("<QQHB")
PIT_HZ = 3_579_545 / 3
BIOS_TICK_US = 65_536 * 1_000_000 / PIT_HZ


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[float], p: float) -> float:
    v = sorted(values)
    if not v:
        return math.nan
    x = (len(v) - 1) * p
    a = int(x)
    return v[a] + (v[min(a + 1, len(v) - 1)] - v[a]) * (x - a)


def stats(values: list[float]) -> dict[str, float]:
    return {"min": round(min(values), 3), "p50": round(percentile(values, .5), 3),
            "p95": round(percentile(values, .95), 3),
            "p99": round(percentile(values, .99), 3), "max": round(max(values), 3)}


def expected_frames(path: Path) -> list[dict]:
    frames = []
    noise_valid, noise_mode = False, 0
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            ix = int(row["frame"])
            assert ix == len(frames)
            periods = [int(row[f"p{i}"]) for i in range(3)]
            volume = int(row["volume"])
            noise = int(row["noise"])
            retrigger = int(row["retrigger"])
            seq = []
            for ch, period in enumerate(periods):
                seq.extend([0x80 | ch << 5 | period & 15,
                            period >> 4 & 63,
                            0x90 | ch << 5 | (volume >> (ch * 4) & 15)])
            if not noise_valid or noise != noise_mode or retrigger:
                seq.append(0xE0 | noise)
                noise_valid, noise_mode = True, noise
            seq.append(0xF0 | (volume >> 12))
            frames.append({"frame": ix, "cycles": int(row["at_cycles"]),
                           "fine": int(row["at_fine"]),
                           "pit": int(row["pit_divisor"]),
                           "messages": int(row["frame_messages"]), "psg": bytes(seq)})
    return frames


def read_trace(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if len(raw) % RECORD.size:
        raise ValueError(f"partial IO record: {len(raw)} bytes is not a multiple of {RECORD.size}")
    out = []
    previous_tsc = -1
    for i, (tsc, rate, port, value) in enumerate(RECORD.iter_unpack(raw)):
        if not rate or tsc < previous_tsc:
            raise ValueError(f"bad TSC/rate at record {i}")
        previous_tsc = tsc
        out.append({"tsc": tsc, "timer_usec": rate, "port": port,
                    "value": value, "us": tsc * (1 << 32) / rate})
    return out


def align(frames: list[dict], psg: list[dict]) -> tuple[int, int, list[dict], dict | None]:
    # The initial 11-byte complete muted frame is distinctive; seek every
    # occurrence, then choose the longest *frame-boundary* match. The first
    # mismatch reports actual and expected bytes without splicing the trace.
    first = frames[0]["psg"]
    stream = bytes(item["value"] for item in psg)
    starts = []
    at = stream.find(first)
    while at >= 0:
        starts.append(at)
        at = stream.find(first, at + 1)
    if not starts:
        raise AssertionError("no exact first prepared frame in PSG stream")
    best = (0, -1, [], None)
    for start in starts:
        pos, matched = start, []
        for frame in frames:
            want = frame["psg"]
            got = stream[pos:pos + len(want)]
            if got != want:
                bad = next((j for j, (a, b) in enumerate(zip(got, want)) if a != b), len(got))
                mismatch = {"frame": frame["frame"], "psg_offset": pos + bad,
                            "expected": want[bad] if bad < len(want) else None,
                            "actual": got[bad] if bad < len(got) else None}
                break
            matched.append({**frame, "psg_start": pos, "psg_end": pos + len(want) - 1,
                            "first_us": psg[pos]["us"],
                            "last_us": psg[pos + len(want) - 1]["us"]})
            pos += len(want)
        else:
            mismatch = None
        if len(matched) > len(best[2]):
            best = (start, pos, matched, mismatch)
    return best


def pit_programs(io: list[dict]) -> list[dict]:
    result = []
    for i, item in enumerate(io):
        if item["port"] != 0x43 or item["value"] != 0xB6:
            continue
        after = [x for x in io[i + 1:i + 5] if x["port"] == 0x42]
        if len(after) < 2:
            result.append({"record": i, "divisor": None, "us": item["us"]})
        else:
            result.append({"record": i, "divisor": after[0]["value"] |
                           after[1]["value"] << 8, "us": item["us"]})
    return result


def absolute_origin(io: list[dict], matched: list[dict]) -> dict:
    markers = [x for x in io if x["port"] == 0xE9 and x["value"] == 0x52]
    if len(markers) != 1:
        raise AssertionError(f"expected exactly one origin marker, found {len(markers)}")
    marker_us = markers[0]["us"]
    # The diagnostic emits 0x52 immediately before reading the song origin,
    # at the beginning of a 36-BIOS-tick countdown.
    origin_us = marker_us + 36 * BIOS_TICK_US
    first = [m["first_us"] - origin_us - m["cycles"] * 1_000_000 / PIT_HZ
             for m in matched]
    last = [m["last_us"] - origin_us - m["cycles"] * 1_000_000 / PIT_HZ
            for m in matched]
    rws_first = [m["first_us"] - origin_us - m["fine"] * 256_000_000 / PIT_HZ
                 for m in matched]
    return {
        "marker_port": "E9", "marker_value": 0x52,
        "marker_us": round(marker_us, 3),
        "countdown_bios_ticks": 36,
        "bios_tick_us": round(BIOS_TICK_US, 6),
        "inferred_music_origin_us": round(origin_us, 3),
        "marker_to_origin_read_bound_us": 500,
        "first_byte_signed_delay_us": stats(first),
        "last_byte_signed_delay_us": stats(last),
        "rws_fine_first_byte_signed_delay_us": stats(rws_first),
        "reference_basis": "at_cycles/PIT_HZ above; serialized RWS at_fine*256/PIT_HZ in rws_fine field (ceil quantization <= 255 PIT cycles)",
        "negative_first_frames": sum(x < 0 for x in first),
        "first_frames_earlier_than_minus_500us": sum(x < -500 for x in first),
        "first_frames_earlier_than_minus_5ms": sum(x < -5_000 for x in first),
        "first_frames_earlier_than_minus_20ms": sum(x < -20_000 for x in first),
        "earliest_first_frame": matched[first.index(min(first))]["frame"],
        "latest_first_frame": matched[first.index(max(first))]["frame"],
        "interpretation": ("Large negative timestamps exceed the marker-to-origin bound and require clock or timestamp-model diagnosis; they do not prove early acoustic output. PIT0 mode-3 half-tick is 27.466 ms." if min(first)<-500 else "No frame precedes the inferred origin schedule beyond its 0.5ms measurement bound."),
    }


MANUAL_RE = re.compile(
    r"^manual_irq\[(\d+)\] key=(\d+) now=(\d+) ago=(\d+) "
    r"irq_tick=(\d+) applied=(\d+) accepted=(\d+) hits_after=(\d+)$", re.M)


def manual_input(io: list[dict], marker_us: float, injection: Path, runlog: Path) -> dict:
    payload = json.loads(injection.read_text())
    if payload.get("error") is not None or len(payload.get("markers", [])) != 1:
        raise AssertionError("injection did not finish with one marker")
    sent = payload["sent"]
    reads = [x for x in io if x["port"] == 0x8060]
    if len(reads) != len(sent):
        raise AssertionError(f"keyboard read count {len(reads)} != sent count {len(sent)}")
    for i, (actual, target) in enumerate(zip(reads, sent)):
        byte = target["scancode"] | (0 if target["down"] else 0x80)
        if actual["value"] != byte:
            raise AssertionError(f"keyboard byte mismatch at {i}: {actual['value']} != {byte}")
    input_delay = [read["us"] - marker_us - send["sent_seconds"] * 1_000_000
                   for read, send in zip(reads, sent)]
    notes = [(read, send) for read, send in zip(reads, sent)
             if send["down"] and "note" in send["detail"]]
    rows = [tuple(map(int, match.groups())) for match in MANUAL_RE.finditer(runlog.read_text())]
    if len(rows) != len(notes) or [r[0] for r in rows] != list(range(len(rows))):
        raise AssertionError("manual RAM trace is incomplete or out of order")
    ticks_from_note0 = []
    bda_offsets = []
    requested_tick_differences = []
    for i, ((read, send), row) in enumerate(zip(notes, rows)):
        _, key, now, ago, irq_tick, applied, accepted, hits_after = row
        detail = send["detail"]
        intended = detail["target_tick"] + detail["offset"]
        if detail["note"] != i or key != send["scancode"]:
            raise AssertionError(f"note order/scancode mismatch at {i}")
        if not irq_tick or applied != now - ago:
            raise AssertionError(f"IRQ timing/application mismatch at note {i}")
        requested_tick_differences.append(applied-intended)
        if abs(applied-intended)>1:
            raise AssertionError(f"host injection missed its target by more than one BIOS tick at note {i}")
        if accepted != (abs(applied-detail["target_tick"]) <= 3):
            raise AssertionError(f"unexpected judgment at note {i}")
        if hits_after != sum(r[6] for r in rows[:i + 1]):
            raise AssertionError(f"hit count mismatch at note {i}")
        bda_offsets.append(irq_tick - applied)
        tick_difference = (read["us"] - notes[0][0]["us"]) / BIOS_TICK_US
        ticks_from_note0.append(tick_difference - (irq_tick - rows[0][4]))
    if len(set(bda_offsets)) != 1 or max(map(abs, ticks_from_note0)) >= 1:
        raise AssertionError("IRQ BIOS ticks do not agree with IO timestamps")
    log = runlog.read_text()
    def field(name: str) -> int:
        match = re.search(rf"\b{re.escape(name)}=(\d+)\b", log)
        if not match:
            raise AssertionError(f"missing RUNLOG field {name}")
        return int(match.group(1))
    if field("mode") != 6 or field("queue_overflow") != 0:
        raise AssertionError("manual mode/queue overflow check failed")
    if field("hits") != sum(r[6] for r in rows) or field("ghosts") != len(rows) - field("hits"):
        raise AssertionError("manual acceptance counters do not match RAM trace")
    return {
        "result": "PASS", "injection": str(injection.relative_to(ROOT)).replace("\\", "/"),
        "requested_vs_actual_applied_tick_differences": requested_tick_differences,
        "judgment_basis": "Actual IRQ BIOS tick and applied now-ago time; host requests may differ by one tick and are not treated as IRQ timestamps.",
        "injection_sha256": sha(injection),
        "runlog": str(runlog.relative_to(ROOT)).replace("\\", "/"),
        "runlog_sha256": sha(runlog),
        "sent_key_events": len(sent), "actual_keyboard_reads": len(reads),
        "all_scancodes_and_up_down_order_match": True,
        "note_keydowns": len(notes), "matched_ram_irq_records": len(rows),
        "accepted_notes": sum(r[6] for r in rows),
        "rejected_intentional_window_edges": len(rows) - sum(r[6] for r in rows),
        "irq_bios_ticks_nonzero": all(r[4] > 0 for r in rows),
        "irq_bios_tick_minus_applied_song_tick": bda_offsets[0],
        "actual_keyboard_read_vs_irq_bios_tick_delta_ticks": stats(ticks_from_note0),
        "applied_equals_now_minus_ago_for_all_notes": True,
        "note_ago_values": sorted(set(r[3] for r in rows)),
        "queue_overflow": field("queue_overflow"),
        "max_input_wait_ticks_all_keys": field("input_wait_ticks"),
        "irq1_makes": field("makes"), "irq1_breaks": field("breaks"),
        "sent_to_actual_keyboard_read_delay_us": stats(input_delay),
        "limitation": (("This run includes a delayed note judged using its queued IRQ age. " if any(r[3] for r in rows) else "All sampled note hits had ago=0, so this run does not exercise delayed-note backdating. ")+f"The final Esc break can be read after game IRQ handler cleanup: {len(reads)} port reads versus {field('IRQ1')} game IRQ1 records."),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path, default=NATIVE)
    parser.add_argument("--schedule", type=Path,
                        default=RAVE / "build/DEMO-CYCLES.csv")
    parser.add_argument("--evidence", type=Path,
                        default=RAVE / "evidence/RAVE-IO-TIMING.json")
    parser.add_argument("--marker-origin", action="store_true",
                        help="use the diagnostic E9/52 countdown marker as an absolute origin")
    parser.add_argument("--manual-injection", type=Path,
                        help="compare injected key events, port 8060 reads and RUNLOG RAM records")
    parser.add_argument("--runlog", type=Path,
                        help="RUNLOG path for --manual-injection (default: native/RUNLOG.TXT)")
    parser.add_argument("--results-sfx", action="store_true", help="require complete song and the original nine-stage results tones after it")
    args = parser.parse_args()
    native, schedule, evidence = args.native.resolve(), args.schedule.resolve(), args.evidence.resolve()
    result_file = native / "RESULT.json"
    if not result_file.exists() or not json.loads(result_file.read_text())["complete"]:
        raise RuntimeError("native capture is still active; will not read IO-TRACE.BIN")
    trace_path = native / "IO-TRACE.BIN"
    frames, io = expected_frames(schedule), read_trace(trace_path)
    psg = [item for item in io if item["port"] == 0xC0]
    start, end, matched, mismatch = align(frames, psg)
    if not matched:
        raise AssertionError("no complete prepared frame matched")
    offset_us = matched[0]["first_us"] - matched[0]["cycles"] * 1_000_000 / PIT_HZ
    first_late = [m["first_us"] - (offset_us + m["cycles"] * 1_000_000 / PIT_HZ)
                  for m in matched]
    last_late = [m["last_us"] - (offset_us + m["cycles"] * 1_000_000 / PIT_HZ)
                 for m in matched]
    span = [m["last_us"] - m["first_us"] for m in matched]
    interbyte = [psg[j + 1]["us"] - psg[j]["us"]
                 for m in matched for j in range(m["psg_start"], m["psg_end"])]
    lower_envelope_us = offset_us + min(first_late)
    lower_late_first = [m["first_us"] -
                        (lower_envelope_us + m["cycles"] * 1_000_000 / PIT_HZ)
                        for m in matched]
    lower_late_last = [m["last_us"] -
                       (lower_envelope_us + m["cycles"] * 1_000_000 / PIT_HZ)
                       for m in matched]
    jitter = [(b["first_us"] - a["first_us"]) -
              (b["cycles"] - a["cycles"]) * 1_000_000 / PIT_HZ
              for a, b in zip(matched, matched[1:])]
    suffix = bytes(x["value"] for x in psg[end:])
    next_prefix = 0
    if len(matched) < len(frames):
        want = frames[len(matched)]["psg"]
        while next_prefix < min(len(suffix), len(want)) and suffix[next_prefix] == want[next_prefix]:
            next_prefix += 1
    cleanup = b"\x9f\xbf\xdf\xff"
    rest = suffix[next_prefix:]
    suffix_class = ("complete" if not suffix else
                    "cleanup_mutes" if not next_prefix and rest and
                    len(rest) % 4 == 0 and rest == cleanup * (len(rest) // 4) else
                    "partial_next_frame_then_cleanup" if next_prefix and
                    len(rest) % 4 == 0 and rest == cleanup * (len(rest) // 4) else
                    "unexpected")
    results_sfx = None
    if args.results_sfx:
        assert len(matched)==len(frames), "results check requires complete unchanged song"
        assert suffix.startswith(cleanup) and suffix.endswith(cleanup), "results must follow song mute and end muted"
        attacks=[];i=0
        while i<len(suffix):
            b=suffix[i]
            if b&0x90==0x80 and b<0xe0:
                assert i+2<len(suffix) and suffix[i+1]<64
                ch=(b>>5)&3;vol=suffix[i+2]
                assert vol&0xf0==0x90+(ch<<5)
                attacks.append((ch,(b&15)+(suffix[i+1]<<4),vol&15));i+=3
            else:
                assert b in range(0x90,0xa0) or b in range(0xb0,0xc0) or b in range(0xd0,0xe0) or b==0xff, hex(b)
                i+=1
        want=[(0,214,4),(0,170,5),(0,143,5),(0,127,5),(0,107,5),(0,95,5),(0,85,5),(0,107,2),(1,143,2),(2,214,3)]
        # Divisors use the existing MIDI45..96 table, preserved byte for byte.
        table=[int(v) for v in re.search(r'midi_div\[52\]=\{(.*?)\}',(Path(__file__).resolve().parents[1]/'src/SFX.H').read_text(),re.S).group(1).replace('\n','').split(',') if v.strip()]
        want=[(0,table[72-45],4)]+[(0,table[n-45],5) for n in [79,82,85,76,79,81,84,86,88]]+[(ch,table[n-45],att) for ch,n,att in [(0,84,2),(1,79,2),(2,72,3)]]
        assert attacks==want,(attacks,want)
        results_sfx={"result":"PASS","tone_attacks":attacks,"psg_bytes":len(suffix),"existing_effects":"opening note, three scripted initials blips, six tally blips, grade triad, original decay and cleanup","song_to_results_first_write_ms":round((psg[end]["us"]-matched[-1]["last_us"])/1000,3)}
        suffix_class="verified_original_results_sfx_then_cleanup"
    # A prepared frame's PIT programming follows its final PSG write. Equal
    # divisors are cached by both frozen LeaseFast and DOS DOSSND.
    expected_pit = []
    expected_pit_frame = []
    last_divisor = 0
    for m in matched:
        if m["pit"] and m["pit"] != last_divisor:
            expected_pit.append(m["pit"])
            expected_pit_frame.append(m)
        last_divisor = m["pit"]
    programs = pit_programs(io)
    # Ignore any setup PIT writes before frame zero or cleanup after the
    # matched PSG prefix; timing ranges disambiguate them.
    upper_us = psg[end]["us"] if end < len(psg) else matched[-1]["last_us"] + 50_000
    selected = [p for p in programs if matched[0]["first_us"] <= p["us"] < upper_us]
    actual_pit = [p["divisor"] for p in selected]
    pit_prefix = 0
    for got, want in zip(actual_pit, expected_pit):
        if got != want:
            break
        pit_prefix += 1
    pit_order = [actual["us"] >= frame["last_us"] and
                 (frame["frame"] + 1 >= len(matched) or
                  actual["us"] < matched[frame["frame"] + 1]["first_us"])
                 for actual, frame in zip(selected, expected_pit_frame)]
    pit_late = [actual["us"] -
                (lower_envelope_us + frame["cycles"] * 1_000_000 / PIT_HZ)
                for actual, frame in zip(selected, expected_pit_frame)]
    result = {
        "result": (("FULL_PASS" if len(matched)==len(frames) else "PREFIX_PASS") if actual_pit == expected_pit and all(pit_order) and
                   suffix_class != "unexpected" else "MISMATCH"),
        "native_result": str(result_file.relative_to(ROOT)).replace("\\", "/"),
        "trace": str(trace_path.relative_to(ROOT)).replace("\\", "/"),
        "trace_sha256": sha(trace_path), "trace_records": len(io),
        "psg_records": len(psg), "reference_frames": len(frames),
        "matched_prefix_frames": len(matched),
        "matched_messages": sum(m["messages"] for m in matched),
        "matched_psg_bytes": end - start,
        "startup_psg_prefix_bytes": start,
        "unmatched_psg_suffix_bytes": len(psg) - end,
        "unmatched_psg_suffix_hex_first32": bytes(x["value"] for x in psg[end:end + 32]).hex(),
        "suffix_class": suffix_class, "results_sfx": results_sfx,
        "partial_next_frame_bytes": next_prefix,
        "first_psg_mismatch": mismatch if suffix_class == "unexpected" else None,
        "first_after_prefix_comparison": mismatch,
        "pit_programs_expected_for_prefix": len(expected_pit),
        "pit_programs_captured_in_range": len(actual_pit),
        "pit_programs_matching_prefix": pit_prefix,
        "pit_programs_in_corresponding_frame_window": sum(pit_order),
        "pit_program_delay_from_earliest_origin_us": stats(pit_late) if pit_late else None,
        "first_pit_mismatch": ({"index": pit_prefix,
                                "expected": expected_pit[pit_prefix] if pit_prefix < len(expected_pit) else None,
                                "actual": actual_pit[pit_prefix] if pit_prefix < len(actual_pit) else None}
                               if actual_pit != expected_pit else None),
        "origin_offset_us_first_frame": round(offset_us, 3),
        "origin_offset_us_earliest_observed_frame": round(lower_envelope_us, 3),
        "first_byte_lateness_us": stats(first_late),
        "last_byte_lateness_us": stats(last_late),
        "first_byte_delay_from_earliest_origin_us": stats(lower_late_first),
        "last_byte_delay_from_earliest_origin_us": stats(lower_late_last),
        "interframe_first_byte_jitter_us": stats(jitter) if jitter else None,
        "frame_psg_emit_span_us": stats(span),
        "within_frame_psg_byte_gap_us": stats(interbyte),
        "final_cleanup_mute_byte_gap_us": (stats([psg[i + 1]["us"] - psg[i]["us"]
                                                   for i in range(len(psg) - 4, len(psg) - 1)])
                                             if len(psg) - end >= 4 else None),
        "maximum_frame_psg_bytes": max(len(m["psg"]) for m in matched),
        "irq_off_duration": "unknown: not logged",
        "timing_basis": "tsc * 2^32 / TIMER_USEC; expected at_cycles / (3579545/3)",
        "limits": "Absolute song-clock origin was not logged: first-frame anchored offsets can be negative and earliest-observed offset is only a lower envelope. The bounded capture is checked through its exact PSG prefix. BIOS IRQ-off duration and physical audio response are not measured.",
    }
    if args.marker_origin:
        result["absolute_origin"] = absolute_origin(io, matched)
        result["limits"] = "Absolute origin is inferred from a marker immediately before the final origin read and a 36-BIOS-tick countdown; marker-to-read uncertainty is under 0.5 ms. The bounded capture is checked through its exact PSG prefix. BIOS IRQ-off duration and physical audio response are not measured."
    if args.manual_injection:
        if not args.marker_origin:
            raise ValueError("--manual-injection requires --marker-origin")
        result["manual_input"] = manual_input(
            io, result["absolute_origin"]["marker_us"],
            args.manual_injection.resolve(),
            (args.runlog or native / "RUNLOG.TXT").resolve())
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['result']}: {len(matched)} frames, {end-start} PSG bytes; "
          f"PIT {pit_prefix}/{len(expected_pit)}; max PSG span {max(span):.1f} us")


if __name__ == "__main__":
    main()
