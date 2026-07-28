import { useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import {
  ArrowLeft,
  Car,
  ExternalLink,
  LoaderCircle,
  MapPin,
  Navigation,
  Store,
  TriangleAlert,
} from "lucide-react";

const TAIWAN_CENTER = [23.7, 121];

function FitMapToPoints({ points }) {
  const map = useMap();

  useEffect(() => {
    if (!points.length) return;
    if (points.length === 1) {
      map.setView(points[0], 15);
      return;
    }
    map.fitBounds(points, { padding: [45, 45], maxZoom: 16 });
  }, [map, points]);

  return null;
}

function FocusSelectedPoint({ point }) {
  const map = useMap();

  useEffect(() => {
    if (!point) return;
    map.flyTo([point.latitude, point.longitude], 17, {
      animate: true,
      duration: 0.65,
    });
  }, [map, point]);

  return null;
}

function pointKey(point) {
  return `${point.kind}:${point.id}`;
}

function MarkerPopup({ point, rank }) {
  return (
    <Popup>
      <div className="map-popup">
        <strong>{rank ? `#${rank} ${point.title}` : point.title}</strong>
        <span>{point.address}</span>
        {point.is_approximate && <em>此為約略位置，並非精確門牌定位。</em>}
        {point.score != null && <b>推薦分數 {Math.round(point.score)}</b>}
        {point.source_url && (
          <a href={point.source_url} target="_blank" rel="noopener noreferrer">
            查看原始刊登 <ExternalLink size={13} />
          </a>
        )}
      </div>
    </Popup>
  );
}

function SidebarPointButton({
  point,
  icon: Icon,
  selected,
  onSelect,
  prefix,
}) {
  return (
    <button
      type="button"
      className={`map-list-item ${selected ? "selected" : ""}`}
      onClick={() => onSelect(point)}
      aria-pressed={selected}
    >
      <Icon size={15} />
      <span>
        <strong>{prefix ? `${prefix} ${point.title}` : point.title}</strong>
        <small>{point.address}</small>
      </span>
      <Navigation size={13} />
    </button>
  );
}

export default function MapView({
  context,
  loading,
  error,
  destinationName,
  onBack,
}) {
  const destination = context?.destination;
  const properties = context?.properties || [];
  const stores = context?.convenience_stores || [];
  const parking = context?.parking_facilities || [];
  const [selectedKey, setSelectedKey] = useState("");
  const allPoints = useMemo(
    () => [destination, ...properties, ...stores, ...parking].filter(Boolean),
    [destination, properties, stores, parking],
  );
  const selectedPoint = useMemo(
    () => allPoints.find((point) => pointKey(point) === selectedKey) || null,
    [allPoints, selectedKey],
  );
  const positions = useMemo(
    () =>
      [destination, ...properties, ...stores, ...parking]
        .filter(Boolean)
        .map((point) => [point.latitude, point.longitude]),
    [destination, properties, stores, parking],
  );

  function selectPoint(point) {
    if (point) setSelectedKey(pointKey(point));
  }

  function selectFirst(points) {
    if (points.length) selectPoint(points[0]);
  }

  return (
    <section className="map-page">
      <div className="map-toolbar">
        <button type="button" className="back-button" onClick={onBack}>
          <ArrowLeft size={18} /> 回推薦排名
        </button>
        <div>
          <span className="eyebrow">MAP & AMENITIES</span>
          <h2>地圖相對位置、超商與停車</h2>
          <p>顯示目的地、前 6 名推薦房源，以及房源 500 公尺內的生活設施。</p>
        </div>
      </div>

      {loading && (
        <div className="map-status">
          <LoaderCircle className="spin" size={28} />
          <strong>正在定位房源與查詢附近超商…</strong>
          <span>第一次載入可能需要幾秒鐘。</span>
        </div>
      )}

      {!loading && error && (
        <div className="map-status map-error">
          <TriangleAlert size={28} />
          <strong>地圖資料暫時無法載入</strong>
          <span>{error}</span>
        </div>
      )}

      {!loading && !error && context && (
        <>
          <div className="map-layout">
            <div className="map-canvas">
              <MapContainer center={TAIWAN_CENTER} zoom={7} scrollWheelZoom>
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <FitMapToPoints points={positions} />
                <FocusSelectedPoint point={selectedPoint} />

                {selectedPoint && (
                  <>
                    <CircleMarker
                      key={`halo-outer-${pointKey(selectedPoint)}`}
                      center={[selectedPoint.latitude, selectedPoint.longitude]}
                      radius={24}
                      className="selected-map-halo selected-map-halo-outer"
                      interactive={false}
                      pathOptions={{
                        color: "#dff485",
                        fillColor: "#dff485",
                        fillOpacity: 0.12,
                        opacity: 0.7,
                        weight: 7,
                      }}
                    />
                    <CircleMarker
                      key={`halo-inner-${pointKey(selectedPoint)}`}
                      center={[selectedPoint.latitude, selectedPoint.longitude]}
                      radius={15}
                      className="selected-map-halo"
                      interactive={false}
                      pathOptions={{
                        color: "#ffffff",
                        fillColor: "#dff485",
                        fillOpacity: 0.24,
                        opacity: 1,
                        weight: 4,
                      }}
                    />
                  </>
                )}

                {destination && (
                  <CircleMarker
                    center={[destination.latitude, destination.longitude]}
                    radius={11}
                    eventHandlers={{ click: () => selectPoint(destination) }}
                    pathOptions={{ color: "#173c2b", fillColor: "#dff485", fillOpacity: 1, weight: 4 }}
                  >
                    <MarkerPopup point={destination} />
                  </CircleMarker>
                )}

                {destination &&
                  properties.map((property) => (
                    <Polyline
                      key={`line-${property.id}`}
                      positions={[
                        [destination.latitude, destination.longitude],
                        [property.latitude, property.longitude],
                      ]}
                      pathOptions={{ color: "#5f816e", opacity: 0.42, weight: 2, dashArray: "6 8" }}
                    />
                  ))}

                {properties.map((property, index) => (
                  <CircleMarker
                    key={property.id}
                    center={[property.latitude, property.longitude]}
                    radius={index === 0 ? 10 : 8}
                    eventHandlers={{ click: () => selectPoint(property) }}
                    pathOptions={{
                      color: index === 0 ? "#2e6648" : "#4e7f62",
                      fillColor: index === 0 ? "#69bd83" : "#a8d6b4",
                      fillOpacity: 0.95,
                      weight: 3,
                    }}
                  >
                    <MarkerPopup point={property} rank={index + 1} />
                  </CircleMarker>
                ))}

                {stores.map((store) => (
                  <CircleMarker
                    key={store.id}
                    center={[store.latitude, store.longitude]}
                    radius={5}
                    eventHandlers={{ click: () => selectPoint(store) }}
                    pathOptions={{ color: "#bd6d28", fillColor: "#f4a94d", fillOpacity: 0.9, weight: 2 }}
                  >
                    <MarkerPopup point={store} />
                  </CircleMarker>
                ))}

                {parking.map((facility) => (
                  <CircleMarker
                    key={facility.id}
                    center={[facility.latitude, facility.longitude]}
                    radius={5}
                    eventHandlers={{ click: () => selectPoint(facility) }}
                    pathOptions={{ color: "#55519a", fillColor: "#918ce0", fillOpacity: 0.9, weight: 2 }}
                  >
                    <MarkerPopup point={facility} />
                  </CircleMarker>
                ))}
              </MapContainer>
              {selectedPoint && (
                <div className="map-selected-card">
                  <span>目前選取</span>
                  <strong>{selectedPoint.title}</strong>
                  <small>{selectedPoint.address}</small>
                  {selectedPoint.is_approximate && (
                    <em>抽象目的地的生活圈代表點</em>
                  )}
                </div>
              )}
            </div>

            <aside className="map-sidebar">
              <div className="map-summary-card">
                <span className="eyebrow">目前視圖</span>
                {destination ? (
                  <SidebarPointButton
                    point={destination}
                    icon={MapPin}
                    selected={selectedKey === pointKey(destination)}
                    onSelect={selectPoint}
                  />
                ) : (
                  <h3>{destinationName}</h3>
                )}
                <div className="map-counts">
                  <button type="button" onClick={() => selectFirst(properties)} disabled={!properties.length}>
                    <MapPin size={18} /><strong>{properties.length}</strong><span>間房源</span>
                  </button>
                  <div className="map-count-static">
                    <Store size={18} /><strong>{stores.length}</strong><span>間超商</span>
                  </div>
                  <div className="map-count-static">
                    <Car size={18} /><strong>{parking.length}</strong><span>處停車</span>
                  </div>
                </div>
              </div>

              <div className="map-legend">
                <h3>圖例</h3>
                <button type="button" onClick={() => selectPoint(destination)} disabled={!destination}>
                  <i className="legend-dot destination" />目的地
                </button>
                <button type="button" onClick={() => selectFirst(properties)} disabled={!properties.length}>
                  <i className="legend-dot property" />推薦房源
                </button>
                <span className="legend-item">
                  <i className="legend-dot store" />便利商店
                </span>
                <span className="legend-item">
                  <i className="legend-dot parking" />停車設施
                </span>
                <small><Navigation size={13} />虛線僅表示相對位置，不代表實際通勤路線。</small>
              </div>
            </aside>
          </div>

          {!!context.warnings?.length && (
            <div className="map-warnings">
              <TriangleAlert size={17} />
              <span>{context.warnings.join(" ")}</span>
            </div>
          )}
        </>
      )}
    </section>
  );
}
