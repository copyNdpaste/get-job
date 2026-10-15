import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "./job-map.css";

export type MapJob = {
  id: number; source: string; company: string; title: string; url: string;
  location: string | null; latitude: number | null; longitude: number | null;
  score_origin?: "ai" | "rules";
  precision: "source" | "region" | "unknown";
  total_fit_score: number | null; application_value_score: number | null;
};
export type MapResponse = { items: MapJob[]; total: number; limit: number; offset: number };

export function JobMap({ data, loading, error, onEvidence }: {
  data?: MapResponse; loading: boolean; error: boolean; onEvidence: (id: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const [preciseOnly, setPreciseOnly] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [tileError, setTileError] = useState(false);
  useEffect(() => {
    if (!container.current) return;
    const instance = L.map(container.current, { scrollWheelZoom: false }).setView([37.5, 127.0], 10);
    map.current = instance;
    const tiles = L.tileLayer(import.meta.env.VITE_MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: import.meta.env.VITE_MAP_ATTRIBUTION || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(instance);
    tiles.on("tileerror", () => setTileError(true));
    const resize = new ResizeObserver(() => instance.invalidateSize());
    resize.observe(container.current);
    return () => { resize.disconnect(); instance.remove(); map.current = null; };
  }, []);
  useEffect(() => {
    if (!map.current) return;
    const instance = map.current;
    const markerJobs = new Map<L.Marker, number[]>();
    const markers = L.markerClusterGroup({
      maxClusterRadius: 45,
      showCoverageOnHover: false,
      spiderfyOnMaxZoom: true,
      iconCreateFunction: (cluster) => {
        const count = cluster.getAllChildMarkers().reduce((sum: number, marker: L.Marker) => sum + (markerJobs.get(marker)?.length ?? 0), 0);
        return L.divIcon({ className: "job-map-pin cluster", html: `<span>${count}</span>`, iconSize: [38, 38], iconAnchor: [19, 19] });
      },
    }).addTo(instance);
    markers.on("clusterclick", (event) => {
      const cluster = (event as L.LeafletEvent & { layer: L.MarkerCluster }).layer;
      setSelected(cluster.getAllChildMarkers().flatMap((marker: L.Marker) => markerJobs.get(marker) ?? []));
    });
    const groups = new Map<string, MapJob[]>();
    for (const job of data?.items ?? []) {
      if (job.latitude == null || job.longitude == null || (preciseOnly && job.precision !== "source")) continue;
      const key = `${job.latitude},${job.longitude}`;
      groups.set(key, [...(groups.get(key) ?? []), job]);
    }
    const points: L.LatLngTuple[] = [];
    for (const jobs of groups.values()) {
      const first = jobs[0];
      const point: L.LatLngTuple = [first.latitude!, first.longitude!];
      points.push(point);
      const approximate = jobs.every((job) => job.precision === "region");
      const marker = L.marker(point, {
        icon: L.divIcon({ className: `job-map-pin ${approximate ? "approximate" : ""}`, html: `<span>${jobs.length}</span>`, iconSize: [32, 32], iconAnchor: [16, 16] }),
        title: `${first.company} · ${jobs.length}개 공고 · ${approximate ? "도시 중심, 실제 근무지 아님" : "원문 좌표"}`,
        keyboard: true,
      });
      markerJobs.set(marker, jobs.map((job) => job.id));
      markers.addLayer(marker);
      marker.on("click", () => setSelected(jobs.map((job) => job.id)));
    }
    setSelected([]);
    if (points.length) instance.fitBounds(L.latLngBounds(points), { padding: [35, 35], maxZoom: 14 });
    return () => { instance.removeLayer(markers); };
  }, [data, preciseOnly]);
  const precise = data?.items.filter((job) => job.precision === "source").length ?? 0;
  const approximate = data?.items.filter((job) => job.precision === "region").length ?? 0;
  const unknown = data?.items.filter((job) => job.precision === "unknown").length ?? 0;
  const jobs = data?.items.filter((job) => selected.length ? selected.includes(job.id) : job.precision === "unknown") ?? [];
  return <section className="job-map-view" aria-label="채용 공고 지도">
    <div className="map-summary" role="status"><strong>{loading ? "위치 불러오는 중…" : error ? "지도 공고 조회 실패" : `원문 좌표 ${precise} · 도시 단위 ${approximate} · 위치 미확인 ${unknown}`}</strong>
      <label><input type="checkbox" checked={preciseOnly} onChange={(event) => setPreciseOnly(event.target.checked)} />원문 좌표만 표시</label>
    </div>
    <p className="map-help">초록 표시는 원문 제공 좌표, 점선 표시는 도시 중심입니다. 도시 중심은 실제 근무지가 아닙니다. 큰 숫자는 주변 위치의 묶음입니다. 확대하면 개별 위치가 나타나고, 표시를 누르면 공고를 확인할 수 있어요.</p>
    {data && data.total > data.items.length && <p role="status">일치 공고 {data.total.toLocaleString()}개 중 정렬 순서에 따라 {data.items.length.toLocaleString()}개를 표시합니다. 필터를 좁혀 나머지 공고도 확인하세요.</p>}
    {tileError && <p role="alert">배경 지도를 불러오지 못했습니다. 공고 목록과 주소 검색 링크는 사용할 수 있어요.</p>}
    <div className="map-layout"><div ref={container} className="job-map-canvas" aria-label="근무지 위치 지도" />
      <aside className="map-job-panel"><h3>{selected.length ? `선택한 위치 · ${jobs.length}개` : `위치 미확인 · ${unknown}개`}</h3>
        {!selected.length && <p>지도 표시를 선택하세요. 좌표 없는 공고는 주소로 검색할 수 있어요.</p>}
        {jobs.map((job) => <article key={job.id}><span>{job.company}</span><button type="button" onClick={() => onEvidence(job.id)}>{job.title}</button><p>{job.location || "근무지 미기재"}</p>
          <small>{job.precision === "region" ? "도시 중심 · 주소 확인 필요" : job.precision === "source" ? "원문 제공 좌표" : "좌표 미확인"} · {job.score_origin === "ai" ? "AI 평가" : "AI 대기 · 규칙"} · 적합도 {job.total_fit_score ?? "—"} · 지원가치 {job.application_value_score ?? "—"}</small>
          <div><a href={job.url} target="_blank" rel="noreferrer">원문 공고 ↗</a>{job.location && <a href={`https://map.naver.com/p/search/${encodeURIComponent(job.location)}`} target="_blank" rel="noreferrer">주소 검색 ↗</a>}</div>
        </article>)}
      </aside></div>
  </section>;
}
