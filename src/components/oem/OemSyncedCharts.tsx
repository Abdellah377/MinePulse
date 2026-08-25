import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

const GRID = "#e8ebef"
const TICK = { fill: "#5f6b74", fontSize: 9 }
export const OEM_PALETTE = ["#3a7bd5", "#e8c800", "#d82010", "#508000", "#8b4513", "#6B4FBF", "#e08a2e", "#5c6670"]

export type OemSeries = { key: string; name: string; color?: string }

export function OemTimeSeriesChart({
  title,
  unit,
  series,
  points,
  legendPosition = "bottom",
  height = 160,
}: {
  title?: string
  unit: string
  series: OemSeries[]
  points: Array<Record<string, unknown>>
  legendPosition?: "bottom" | "right"
  height?: number
}) {
  const fmtTs = (v: unknown) => {
    if (typeof v !== "string") return ""
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return v
    return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
  }

  return (
    <div className="flex shrink-0 flex-col border-b border-[#d0d5dc] bg-white">
      {title ? (
        <p className="shrink-0 px-1.5 py-0.5 text-[11px] font-semibold leading-4 text-[#222]">
          {title} <span className="font-normal text-[#6b7280]">({unit})</span>
        </p>
      ) : null}
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%" debounce={40}>
          <LineChart
            data={points}
            syncId="oem-sync"
            margin={{
              left: 4,
              right: legendPosition === "right" ? 120 : 8,
              top: 4,
              bottom: legendPosition === "bottom" ? 18 : 2,
            }}
          >
            <CartesianGrid stroke={GRID} strokeDasharray="2 2" />
            <XAxis
              dataKey="ts"
              tick={TICK}
              tickFormatter={fmtTs}
              minTickGap={40}
              axisLine={{ stroke: "#c5cad1" }}
              tickLine={false}
              height={18}
            />
            <YAxis tick={TICK} axisLine={{ stroke: "#c5cad1" }} tickLine={false} width={40} />
            <Tooltip
              isAnimationActive={false}
              contentStyle={{
                background: "#fff",
                border: "1px solid #d0d5dc",
                borderRadius: 0,
                fontSize: 10,
                padding: "4px 6px",
              }}
              labelFormatter={(l) => (typeof l === "string" ? new Date(l).toLocaleString("fr-FR") : String(l))}
            />
            <Legend
              layout={legendPosition === "right" ? "vertical" : "horizontal"}
              align={legendPosition === "right" ? "right" : "center"}
              verticalAlign={legendPosition === "right" ? "middle" : "bottom"}
              wrapperStyle={{ fontSize: 10, padding: 0 }}
              iconSize={8}
            />
            {series.map((s, i) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.name}
                stroke={s.color ?? OEM_PALETTE[i % OEM_PALETTE.length]}
                strokeWidth={1.25}
                dot={false}
                isAnimationActive={false}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export function OemSynchronizedCharts({
  charts,
  points,
  emptyMessage,
  legendPosition = "bottom",
  bandHeight,
}: {
  charts: Array<{ title: string; unit: string; series: OemSeries[] }>
  points: Array<Record<string, unknown>>
  emptyMessage: string
  legendPosition?: "bottom" | "right"
  bandHeight?: number
}) {
  if (!points.length) {
    return <p className="px-2 py-3 text-left text-[11px] text-[#6b7280]">{emptyMessage}</p>
  }
  const h =
    bandHeight ??
    (charts.length <= 2 ? 220 : charts.length === 3 ? 180 : Math.max(120, Math.min(160, 520 / charts.length)))

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-white">
      {charts.map((chart) => (
        <OemTimeSeriesChart
          key={chart.title}
          title={chart.title}
          unit={chart.unit}
          series={chart.series}
          points={points}
          legendPosition={legendPosition}
          height={h}
        />
      ))}
    </div>
  )
}

export { OemSynchronizedCharts as OemSyncedCharts }
