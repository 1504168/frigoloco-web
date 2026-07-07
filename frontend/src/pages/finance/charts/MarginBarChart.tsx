import * as React from 'react'
import * as d3 from 'd3'
import { useMeasuredWidth } from '@/pages/finance/charts/useMeasuredWidth'

/** One labelled bar (net margin in euros for a fridge / category / supplier). */
export interface MarginBar {
  label: string
  value: number
}

export interface MarginBarChartProps {
  data: MarginBar[]
  /** Row height in px per bar. */
  rowHeight?: number
}

const MARGIN = { top: 4, right: 64, bottom: 4, left: 140 }
const EURO = d3.format(',.0f')

/**
 * Horizontal net-margin bar chart. Positive bars use series-1 (blue), negative
 * bars use the critical token (red), matching the mockup's margin-by-category
 * and margin-by-fridge charts. Rendered with d3.
 */
export function MarginBarChart({ data, rowHeight = 26 }: MarginBarChartProps) {
  const [ref, width] = useMeasuredWidth<HTMLDivElement>()
  const svgRef = React.useRef<SVGSVGElement>(null)
  const height = MARGIN.top + MARGIN.bottom + data.length * rowHeight

  React.useEffect(() => {
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    if (!width || data.length === 0) return

    const innerW = width - MARGIN.left - MARGIN.right
    const root = svg
      .attr('viewBox', `0 0 ${width} ${height}`)
      .append('g')
      .attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

    const extent = d3.extent(data, (d) => d.value) as [number, number]
    const maxAbs = Math.max(Math.abs(extent[0] ?? 0), Math.abs(extent[1] ?? 0), 1)
    const x = d3.scaleLinear().domain([-maxAbs, maxAbs]).range([0, innerW])

    const y = d3
      .scaleBand<string>()
      .domain(data.map((d) => d.label))
      .range([0, data.length * rowHeight])
      .padding(0.28)

    const zero = x(0)

    // Baseline at zero.
    root
      .append('line')
      .attr('x1', zero)
      .attr('x2', zero)
      .attr('y1', 0)
      .attr('y2', data.length * rowHeight)
      .style('stroke', 'var(--baseline)')

    // Bars.
    root
      .append('g')
      .selectAll('rect')
      .data(data)
      .join('rect')
      .attr('y', (d) => y(d.label) ?? 0)
      .attr('height', y.bandwidth())
      .attr('x', (d) => (d.value >= 0 ? zero : x(d.value)))
      .attr('width', (d) => Math.abs(x(d.value) - zero))
      .attr('rx', 2)
      .style('fill', (d) => (d.value >= 0 ? 'var(--series-1)' : 'var(--critical)'))

    // Row labels (left).
    root
      .append('g')
      .selectAll('text')
      .data(data)
      .join('text')
      .attr('x', -8)
      .attr('y', (d) => (y(d.label) ?? 0) + y.bandwidth() / 2)
      .attr('dy', '0.35em')
      .attr('text-anchor', 'end')
      .style('fill', 'var(--ink-2)')
      .style('font-size', '11px')
      .text((d) => (d.label.length > 20 ? `${d.label.slice(0, 19)}…` : d.label))

    // Value labels (at bar end).
    root
      .append('g')
      .selectAll('text')
      .data(data)
      .join('text')
      .attr('x', (d) => (d.value >= 0 ? x(d.value) + 6 : x(d.value) - 6))
      .attr('y', (d) => (y(d.label) ?? 0) + y.bandwidth() / 2)
      .attr('dy', '0.35em')
      .attr('text-anchor', (d) => (d.value >= 0 ? 'start' : 'end'))
      .style('fill', (d) => (d.value >= 0 ? 'var(--good-text)' : 'var(--critical)'))
      .style('font-size', '10px')
      .style('font-variant-numeric', 'tabular-nums')
      .text((d) => `€${EURO(d.value)}`)
  }, [data, width, height, rowHeight])

  return (
    <div ref={ref} className="w-full">
      <svg ref={svgRef} width="100%" height={height} role="img" aria-label="Net margin by group" />
    </div>
  )
}
