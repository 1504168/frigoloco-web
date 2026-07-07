import * as React from 'react'
import * as d3 from 'd3'
import { useMeasuredWidth } from '@/pages/finance/charts/useMeasuredWidth'

/** One week's point in the trend chart. */
export interface TrendPoint {
  label: string
  /** Turnover ex-VAT in euros. */
  turnover: number
  /** Net margin as a fraction (0.09 = 9%); null when the week had no activity. */
  marginPct: number | null
}

export interface TrendChartProps {
  data: TrendPoint[]
  height?: number
}

const MARGIN = { top: 16, right: 52, bottom: 28, left: 56 }

/**
 * Dual-axis weekly trend: turnover ex-VAT as a line on the left € axis
 * (series-1) and net margin % on the right axis (series-2). Rendered with d3.
 */
export function TrendChart({ data, height = 240 }: TrendChartProps) {
  const [ref, width] = useMeasuredWidth<HTMLDivElement>()
  const svgRef = React.useRef<SVGSVGElement>(null)

  React.useEffect(() => {
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    if (!width || data.length === 0) return

    const innerW = width - MARGIN.left - MARGIN.right
    const innerH = height - MARGIN.top - MARGIN.bottom
    const root = svg
      .attr('viewBox', `0 0 ${width} ${height}`)
      .append('g')
      .attr('transform', `translate(${MARGIN.left},${MARGIN.top})`)

    const x = d3
      .scalePoint<string>()
      .domain(data.map((d) => d.label))
      .range([0, innerW])
      .padding(0.5)

    const maxTurnover = d3.max(data, (d) => d.turnover) ?? 0
    const yLeft = d3.scaleLinear().domain([0, maxTurnover * 1.15 || 1]).nice().range([innerH, 0])

    const marginValues = data.map((d) => d.marginPct).filter((v): v is number => v !== null)
    const minMargin = Math.min(0, d3.min(marginValues) ?? 0)
    const maxMargin = Math.max(0.05, d3.max(marginValues) ?? 0.1)
    const yRight = d3.scaleLinear().domain([minMargin, maxMargin * 1.15]).nice().range([innerH, 0])

    // Horizontal gridlines from the left axis.
    root
      .append('g')
      .selectAll('line')
      .data(yLeft.ticks(4))
      .join('line')
      .attr('x1', 0)
      .attr('x2', innerW)
      .attr('y1', (d) => yLeft(d))
      .attr('y2', (d) => yLeft(d))
      .style('stroke', 'var(--grid)')
      .style('stroke-width', 1)

    // Zero line for margin axis when it dips negative.
    if (minMargin < 0) {
      root
        .append('line')
        .attr('x1', 0)
        .attr('x2', innerW)
        .attr('y1', yRight(0))
        .attr('y2', yRight(0))
        .style('stroke', 'var(--baseline)')
        .style('stroke-dasharray', '3 3')
    }

    // X axis labels.
    root
      .append('g')
      .attr('transform', `translate(0,${innerH})`)
      .call(d3.axisBottom(x).tickSize(0))
      .call((g) => g.select('.domain').remove())
      .selectAll('text')
      .style('fill', 'var(--ink-3)')
      .style('font-size', '10px')

    // Left € axis.
    root
      .append('g')
      .call(
        d3
          .axisLeft(yLeft)
          .ticks(4)
          .tickFormat((d) => `€${d3.format('~s')(d as number)}`),
      )
      .call((g) => g.select('.domain').remove())
      .call((g) => g.selectAll('.tick line').remove())
      .selectAll('text')
      .style('fill', 'var(--series-1)')
      .style('font-size', '10px')

    // Right % axis.
    root
      .append('g')
      .attr('transform', `translate(${innerW},0)`)
      .call(
        d3
          .axisRight(yRight)
          .ticks(4)
          .tickFormat((d) => d3.format('.0%')(d as number)),
      )
      .call((g) => g.select('.domain').remove())
      .call((g) => g.selectAll('.tick line').remove())
      .selectAll('text')
      .style('fill', 'var(--series-2)')
      .style('font-size', '10px')

    // Turnover line (left axis).
    const turnoverLine = d3
      .line<TrendPoint>()
      .x((d) => x(d.label) ?? 0)
      .y((d) => yLeft(d.turnover))
    root
      .append('path')
      .datum(data)
      .attr('fill', 'none')
      .attr('d', turnoverLine)
      .style('stroke', 'var(--series-1)')
      .style('stroke-width', 2)

    root
      .append('g')
      .selectAll('circle')
      .data(data)
      .join('circle')
      .attr('cx', (d) => x(d.label) ?? 0)
      .attr('cy', (d) => yLeft(d.turnover))
      .attr('r', 3)
      .style('fill', 'var(--series-1)')

    // Margin % line (right axis) — split into segments across null gaps.
    const marginLine = d3
      .line<TrendPoint>()
      .defined((d) => d.marginPct !== null)
      .x((d) => x(d.label) ?? 0)
      .y((d) => yRight(d.marginPct ?? 0))
    root
      .append('path')
      .datum(data)
      .attr('fill', 'none')
      .attr('d', marginLine)
      .style('stroke', 'var(--series-2)')
      .style('stroke-width', 2)

    root
      .append('g')
      .selectAll('circle')
      .data(data.filter((d) => d.marginPct !== null))
      .join('circle')
      .attr('cx', (d) => x(d.label) ?? 0)
      .attr('cy', (d) => yRight(d.marginPct ?? 0))
      .attr('r', 3)
      .style('fill', 'var(--series-2)')
  }, [data, width, height])

  return (
    <div ref={ref} className="w-full">
      <svg ref={svgRef} width="100%" height={height} role="img" aria-label="Weekly turnover and net margin trend" />
    </div>
  )
}
