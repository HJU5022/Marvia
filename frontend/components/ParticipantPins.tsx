"use client";

// 참석자 출발지 핀.
// 09-18 결정: 로그인한 사람이면 누구 핀이든 끌 수 있다 (SDD 7절). 소유권은 "이 핀이 누구 것인가"라는
// 표시일 뿐이라 색으로만 구분하고 수정을 막지 않는다. 대신 누가 마지막에 고쳤는지 화면에 남긴다.

import { useEffect } from "react";
import { nameLabel, pinImage, type Kakao } from "@/lib/kakao";
import type { AgentResponse } from "@/types/agent";

export type Viewer = { role: "organizer" } | { role: "participant"; userId: string };

export interface ParticipantPin {
  name: string;
  lng: number;
  lat: number;
  confidence: number;
  owner_user_id: string | null;
}

// 수정은 누구나 한다 (SDD 7절, 09-18 결정). 이 함수는 "내 핀인가"를 색으로 구분할 때만 쓴다.
export function isMine(viewer: Viewer, owner: string | null): boolean {
  return viewer.role === "participant" && owner !== null && owner === viewer.userId;
}

export const PIN_COLORS = {
  editable: "#2563eb",
  lowConfidence: "#d97706",
  mine: "#0f766e",
  locked: "#9ca3af",
  selectedStroke: "#111827",
};

const LOW_CONFIDENCE = 0.8;

// 응답의 geocoded(kind=participant) 좌표에 slots 의 소유자를 붙인다. moved 는 화면에서 옮긴 좌표.
export function pinsFrom(
  response: AgentResponse | null,
  moved: Record<string, [number, number]>,
): ParticipantPin[] {
  if (!response?.geocoded) return [];
  return response.geocoded
    .filter((g) => g.kind === "participant")
    .map((g) => {
      const owner = response.slots?.participants.find((p) => p.name === g.name)?.owner_user_id ?? null;
      const m = moved[g.name];
      return {
        name: g.name,
        lng: m ? m[0] : g.lng,
        lat: m ? m[1] : g.lat,
        confidence: m ? 1 : g.confidence,
        owner_user_id: owner,
      };
    });
}

interface Props {
  kakao: Kakao;
  map: Kakao;
  pins: ParticipantPin[];
  viewer: Viewer;
  selected: string | null;
  onSelect: (name: string) => void;
  onMove: (name: string, lng: number, lat: number) => void;
}

export default function ParticipantPins({ kakao, map, pins, viewer, selected, onSelect, onMove }: Props) {
  useEffect(() => {
    const cleanups: (() => void)[] = [];
    for (const pin of pins) {
      const mine = isMine(viewer, pin.owner_user_id);
      const low = pin.confidence < LOW_CONFIDENCE;
      const fill = low ? PIN_COLORS.lowConfidence : mine ? PIN_COLORS.mine : PIN_COLORS.editable;
      const isSelected = selected === pin.name;
      const marker = new kakao.maps.Marker({
        map,
        position: new kakao.maps.LatLng(pin.lat, pin.lng),
        image: pinImage(kakao, {
          fill,
          stroke: isSelected ? PIN_COLORS.selectedStroke : "#ffffff",
          label: pin.name.slice(0, 1),
          shape: "drop",
        }),
        draggable: true,  // 누구 핀이든 끌 수 있다 (SDD 7절, 09-18 결정)
        clickable: true,
        zIndex: isSelected ? 6 : 5,
        // 커서 구분은 app/globals.css 가 title 끝말로 한다
        title: `${pin.name}${mine ? " · 나" : ""} (드래그로 이동)`,
      });
      const label = nameLabel(
        kakao,
        map,
        pin.lng,
        pin.lat,
        low ? `${pin.name} · 위치 확인 필요` : mine ? `${pin.name} · 나` : pin.name,
      );

      const onDragEnd = () => {
        const pos = marker.getPosition();
        onMove(pin.name, pos.getLng(), pos.getLat());
      };
      const onDrag = () => label.setPosition(marker.getPosition());
      const onClick = () => onSelect(pin.name);
      kakao.maps.event.addListener(marker, "drag", onDrag);
      kakao.maps.event.addListener(marker, "dragend", onDragEnd);
      kakao.maps.event.addListener(marker, "click", onClick);

      cleanups.push(() => {
        kakao.maps.event.removeListener(marker, "drag", onDrag);
        kakao.maps.event.removeListener(marker, "dragend", onDragEnd);
        kakao.maps.event.removeListener(marker, "click", onClick);
        marker.setMap(null);
        label.setMap(null);
      });
    }
    return () => cleanups.forEach((fn) => fn());
  }, [kakao, map, pins, viewer, selected, onSelect, onMove]);

  return null;
}
