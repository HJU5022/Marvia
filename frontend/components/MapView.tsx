"use client";

// 카카오맵 한 장. 응답 stage 에 따라 참석자 핀, 집결 후보 핀, 픽업 핀, 경로선을 찍는다 (SDD 2절).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadKakao, nameLabel, pinImage, type Kakao, type PinStyle } from "@/lib/kakao";
import type { AgentResponse, CandidateKind, ParticipantResult } from "@/types/agent";
import ParticipantPins, { PIN_COLORS, type ParticipantPin, type Viewer } from "./ParticipantPins";
import RouteLines, { ROUTE_STYLES } from "./RouteLines";

const DEFAULT_CENTER = { lat: 36.35, lng: 127.8 }; // 국토 중앙쯤. 핀이 생기면 bounds 로 옮긴다
const ALL_ROUTES_MAX = 4;

export const CANDIDATE_STYLES: Record<CandidateKind, { fill: string; label: string }> = {
  gate: { fill: "#b91c1c", label: "위병소·정문" },
  lobby: { fill: "#7c3aed", label: "로비" },
  landmark: { fill: "#0f766e", label: "랜드마크" },
  pier: { fill: "#0369a1", label: "부두" },
  hq: { fill: "#a16207", label: "본사" },
};

interface PlacePin {
  key: string;
  lng: number;
  lat: number;
  text: string;
  style: PinStyle;
  zIndex: number;
  showLabel: boolean; // 핀이 몰리면 이름표가 겹치므로 필요한 핀에만 붙인다. 나머지는 title 로 본다
  onClick?: () => void;
}

interface Props {
  response: AgentResponse | null;
  participantPins: ParticipantPin[];
  viewer: Viewer;
  selectedRank: number | null;
  onSelectRank: (rank: number) => void;
  onMove: (name: string, lng: number, lat: number) => void;
}

export default function MapView({ response, participantPins, viewer, selectedRank, onSelectRank, onMove }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [kakao, setKakao] = useState<Kakao | null>(null);
  const [map, setMap] = useState<Kakao | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  // SDK 로드와 지도 생성
  useEffect(() => {
    let alive = true;
    loadKakao()
      .then((k) => {
        if (!alive || !box.current) return;
        const m = new k.maps.Map(box.current, {
          center: new k.maps.LatLng(DEFAULT_CENTER.lat, DEFAULT_CENTER.lng),
          level: 12,
        });
        m.addControl(new k.maps.ZoomControl(), k.maps.ControlPosition.RIGHT);
        setKakao(k);
        setMap(m);
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, []);

  // 패널 크기가 바뀌면 지도 다시 배치
  useEffect(() => {
    if (!map || !box.current) return;
    const ro = new ResizeObserver(() => map.relayout());
    ro.observe(box.current);
    return () => ro.disconnect();
  }, [map]);

  const stage = response?.stage ?? null;
  const result = response?.result ?? null;
  const showParticipants = stage === "need_confirm" || stage === "done";
  const showCandidates = stage === "done" || stage === "failed";
  const participantCount = response?.slots?.participants.length ?? 0;

  // 경로선 토글: 4명 이하면 기본 켬, 5명 이상이면 기본 끔
  const [showRoutes, setShowRoutes] = useState(true);
  useEffect(() => {
    setShowRoutes(participantCount <= ALL_ROUTES_MAX);
    setSelected(null);
  }, [participantCount, response?.session_id]);

  const rankRows: ParticipantResult[] = useMemo(() => {
    if (stage !== "done" || !result) return [];
    return result.per_participant.filter((r) => r.candidate_rank === selectedRank);
  }, [stage, result, selectedRank]);

  // via_pickup 인 사람은 선을 그리지 않는다. 운전자 선이 픽업 지점을 지난다.
  const visibleRows = useMemo(() => {
    const drawable = rankRows.filter((r) => !r.via_pickup);
    if (showRoutes) return drawable;
    return selected ? drawable.filter((r) => r.name === selected) : [];
  }, [rankRows, selected, showRoutes]);

  const placePins: PlacePin[] = useMemo(() => {
    const out: PlacePin[] = [];
    if (showCandidates && result) {
      for (const c of result.candidates) {
        const s = CANDIDATE_STYLES[c.kind];
        const active = c.rank !== null && c.rank === selectedRank;
        out.push({
          key: `cand:${c.name}`,
          lng: c.lng,
          lat: c.lat,
          text: `${c.rank ? `${c.rank}순위 ` : ""}${c.name}${c.access_ok ? "" : " (출입 불가)"}`,
          style: {
            fill: c.access_ok ? s.fill : PIN_COLORS.locked,
            stroke: active ? PIN_COLORS.selectedStroke : "#ffffff",
            label: c.rank ? String(c.rank) : "?",
            shape: "square",
          },
          zIndex: active ? 8 : 7,
          showLabel: active || c.rank === null,
          onClick: c.rank !== null ? () => onSelectRank(c.rank as number) : undefined,
        });
      }
    }
    if (stage === "done" && response) {
      const geocoded = response.geocoded ?? [];
      for (const g of geocoded) {
        if (g.kind === "destination" || g.kind === "rendezvous") {
          out.push({
            key: `${g.kind}:${g.name}`,
            lng: g.lng,
            lat: g.lat,
            text: g.kind === "destination" ? `목적지 ${g.name}` : `집결지 ${g.name}`,
            style: { fill: "#111827", stroke: "#ffffff", label: g.kind === "destination" ? "목" : "집", shape: "circle" },
            zIndex: 4,
            showLabel: false,
          });
        }
      }
      // 픽업 지점: 지오코딩 결과가 있으면 그 좌표, 없으면 태워지는 사람 경로의 첫 점(탑승 지점)
      const pickupPins = geocoded.filter((g) => g.kind === "pickup");
      for (const row of rankRows.filter((r) => r.via_pickup)) {
        const person = response.slots?.participants.find((p) => p.name === row.name);
        const place = person?.pickup_at ?? "픽업 지점";
        const hit = pickupPins.find((g) => g.name === place);
        const point = hit ? [hit.lng, hit.lat] : row.polyline[0];
        if (!point) continue;
        out.push({
          key: `pickup:${row.name}`,
          lng: point[0],
          lat: point[1],
          text: `${place} · ${row.name} 탑승${person?.pickup ? ` (${person.pickup} 차량)` : ""}`,
          style: { fill: "#ea580c", stroke: "#ffffff", label: "P", shape: "circle" },
          zIndex: 6,
          showLabel: true,
        });
      }
    }
    return out;
  }, [showCandidates, result, stage, response, rankRows, selectedRank, onSelectRank]);

  // 후보·픽업·목적지 핀
  useEffect(() => {
    if (!kakao || !map) return;
    const cleanups = placePins.map((p) => {
      const marker = new kakao.maps.Marker({
        map,
        position: new kakao.maps.LatLng(p.lat, p.lng),
        image: pinImage(kakao, p.style),
        clickable: Boolean(p.onClick),
        zIndex: p.zIndex,
        title: p.text,
      });
      const label = p.showLabel ? nameLabel(kakao, map, p.lng, p.lat, p.text) : null;
      if (p.onClick) kakao.maps.event.addListener(marker, "click", p.onClick);
      return () => {
        if (p.onClick) kakao.maps.event.removeListener(marker, "click", p.onClick);
        marker.setMap(null);
        label?.setMap(null);
      };
    });
    return () => cleanups.forEach((fn) => fn());
  }, [kakao, map, placePins]);

  const shownParticipants = showParticipants ? participantPins : [];

  // 핀 구성이 바뀌면(좌표 이동이 아니라 핀이 생기거나 사라지면) 전체가 보이게 맞춘다
  const boundsKey = useMemo(
    () =>
      [...shownParticipants.map((p) => `p:${p.name}`), ...placePins.map((p) => p.key)].sort().join("|") +
      `#${response?.trace_id ?? ""}`,
    [shownParticipants, placePins, response?.trace_id],
  );
  const pointsRef = useRef<[number, number][]>([]);
  pointsRef.current = [
    ...shownParticipants.map((p) => [p.lng, p.lat] as [number, number]),
    ...placePins.map((p) => [p.lng, p.lat] as [number, number]),
  ];
  useEffect(() => {
    if (!kakao || !map) return;
    const pts = pointsRef.current;
    if (pts.length === 0) return;
    if (pts.length === 1) {
      map.setCenter(new kakao.maps.LatLng(pts[0][1], pts[0][0]));
      map.setLevel(5);
      return;
    }
    const bounds = new kakao.maps.LatLngBounds();
    pts.forEach(([lng, lat]) => bounds.extend(new kakao.maps.LatLng(lat, lng)));
    map.setBounds(bounds, 60, 60, 60, 60);
  }, [kakao, map, boundsKey]);

  const onSelectParticipant = useCallback(
    (name: string) => setSelected((cur) => (cur === name ? null : name)),
    [],
  );

  const hasRoutes = rankRows.some((r) => !r.via_pickup && r.polyline.length > 1);

  return (
    <div className="map-wrap">
      <div ref={box} className="map-root" />
      {error && <div className="map-error">{error}</div>}
      {!error && !map && <div className="map-loading">지도를 불러오는 중…</div>}

      {kakao && map && (
        <>
          <ParticipantPins
            kakao={kakao}
            map={map}
            pins={shownParticipants}
            viewer={viewer}
            selected={selected}
            onSelect={onSelectParticipant}
            onMove={onMove}
          />
          <RouteLines kakao={kakao} map={map} rows={visibleRows} highlighted={selected} />
        </>
      )}

      {hasRoutes && (
        <div className="map-panel">
          <label className="toggle">
            <input
              type="checkbox"
              checked={showRoutes}
              onChange={(e) => {
                setShowRoutes(e.target.checked);
                setSelected(null);
              }}
            />
            경로선 보기
          </label>
          <ul className="legend">
            {Object.values(ROUTE_STYLES).map((s) => (
              <li key={s.label}>
                <span
                  className="legend-line"
                  style={{ borderTopColor: s.color, borderTopStyle: s.style === "solid" ? "solid" : "dashed" }}
                />
                {s.label}
              </li>
            ))}
          </ul>
          <p className="hint">
            {showRoutes
              ? selected
                ? `${selected} 님 경로 강조 중. 핀을 다시 누르면 해제`
                : "참석자 핀을 누르면 그 사람 경로를 강조합니다"
              : selected
                ? `${selected} 님 경로만 표시 중. 핀을 다시 누르면 해제`
                : "참석자 핀을 누르면 그 사람 경로만 보입니다"}
          </p>
        </div>
      )}
    </div>
  );
}
