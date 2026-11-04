/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {Component, OnInit, AfterViewInit, ViewChild, ElementRef, ChangeDetectorRef} from '@angular/core';
import {MatTableDataSource} from '@angular/material/table';
import {MatSnackBar} from '@angular/material/snack-bar';
import {forkJoin} from 'rxjs';
import * as d3 from 'd3';
import {
  TokenUsageService,
  TokenUsageRowV2,
  TokenUsageSummary,
  BillingUnitsSummary,
} from './token-usage.service';

function toIsoDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

@Component({
  selector: 'app-token-usage-management',
  templateUrl: './token-usage.component.html',
  styleUrls: ['./token-usage.component.scss'],
})
export class TokenUsageManagementComponent implements OnInit, AfterViewInit {
  @ViewChild('dailyChartContainer') dailyChartContainer!: ElementRef;

  isLoading = false;

  // TOKEN_USAGE_DASHBOARD_V2: defaults to the last 30 days; the user can
  // widen this to any custom range, including a full year, via the
  // date-range picker (data volumes as of Nov 2026 are small -- a few
  // thousand rows per quarter -- so no server-side limit is applied).
  startDate: Date = (() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return d;
  })();
  endDate: Date = new Date();

  summary: TokenUsageSummary | null = null;
  billingUnits: BillingUnitsSummary | null = null;

  detailDataSource = new MatTableDataSource<TokenUsageRowV2>();
  detailDisplayedColumns: string[] = [
    'timestamp',
    'platform',
    'userEmail',
    'model',
    'total',
    'costUsd',
  ];

  byModelDisplayedColumns: string[] = ['model', 'tokens', 'calls', 'costUsd'];
  byUserDisplayedColumns: string[] = ['userEmail', 'tokens', 'calls', 'costUsd'];
  billingUnitsDisplayedColumns: string[] = [
    'platform',
    'model',
    'unitType',
    'quantity',
    'calls',
    'costUsd',
  ];

  constructor(
    private tokenUsageService: TokenUsageService,
    private snackBar: MatSnackBar,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.loadAll();
  }

  ngAfterViewInit(): void {}

  get grandTotalCostUsd(): number {
    const tokenCost = this.summary?.totalCostUsd || 0;
    const mediaCost = this.billingUnits?.totalCostUsd || 0;
    return tokenCost + mediaCost;
  }

  onDateRangeChange(): void {
    this.loadAll();
  }

  loadAll(): void {
    const start = toIsoDate(this.startDate);
    const end = toIsoDate(this.endDate);
    this.isLoading = true;

    forkJoin({
      rows: this.tokenUsageService.getTokenUsageV2(start, end),
      summary: this.tokenUsageService.getTokenUsageSummary(start, end),
      billingUnits: this.tokenUsageService.getBillingUnitsSummary(start, end),
    }).subscribe({
      next: ({rows, summary, billingUnits}) => {
        this.detailDataSource.data = rows;
        this.summary = summary;
        this.billingUnits = billingUnits;
        this.isLoading = false;
        this.cdr.detectChanges();
        this.renderDailyChart(summary.daily);
      },
      error: err => {
        console.error('Failed to load token usage dashboard', err);
        this.snackBar.open('Failed to load token usage dashboard', 'Close', {
          duration: 3000,
        });
        this.isLoading = false;
      },
    });
  }

  private showNoDataMessage(element: HTMLElement): void {
    d3.select(element).selectAll('*').remove();
    d3.select(element)
      .append('div')
      .attr('class', 'text-center py-8 text-neutral-400')
      .text('No daily data for this range.');
  }

  private renderDailyChart(data: {date: string; tokens: number; costUsd: number}[]): void {
    if (!this.dailyChartContainer) return;
    const element = this.dailyChartContainer.nativeElement;
    if (data.length === 0) {
      this.showNoDataMessage(element);
      return;
    }
    d3.select(element).selectAll('*').remove();

    const margin = {top: 20, right: 40, bottom: 60, left: 60};
    const width = element.offsetWidth - margin.left - margin.right;
    const height = 350 - margin.top - margin.bottom;

    const svg = d3
      .select(element)
      .append('svg')
      .attr('width', width + margin.left + margin.right)
      .attr('height', height + margin.top + margin.bottom)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3
      .scaleBand()
      .domain(data.map(d => d.date))
      .range([0, width])
      .padding(0.2);

    const y = d3
      .scaleLinear()
      .domain([0, d3.max(data, d => d.costUsd) || 0])
      .nice()
      .range([height, 0]);

    d3.select('body').selectAll('.token-usage-chart-tooltip').remove();
    const tooltip = d3
      .select('body')
      .append('div')
      .attr(
        'class',
        'token-usage-chart-tooltip absolute bg-zinc-800 text-white border border-zinc-700 rounded px-2 py-1 opacity-0 pointer-events-none text-sm',
      )
      .style('z-index', '1000');

    const area = d3
      .area<{date: string; tokens: number; costUsd: number}>()
      .x(d => x(d.date)! + x.bandwidth() / 2)
      .y0(height)
      .y1(d => y(d.costUsd));

    svg
      .append('path')
      .datum(data)
      .attr('d', area)
      .style('fill', '#3b82f6')
      .style('opacity', 0.8);

    const hoverLine = svg
      .append('line')
      .attr('y1', 0)
      .attr('y2', height)
      .style('stroke', '#9ca3af')
      .style('stroke-width', '1px')
      .style('stroke-dasharray', '3, 3')
      .style('opacity', 0);

    svg
      .selectAll('.hover-rect')
      .data(data)
      .join('rect')
      .attr('class', 'hover-rect')
      .attr('x', d => x(d.date)!)
      .attr('width', x.bandwidth())
      .attr('y', 0)
      .attr('height', height)
      .style('fill', 'transparent')
      .style('pointer-events', 'all')
      .style('cursor', 'pointer')
      .on('mouseover', () => {
        tooltip.style('opacity', 1);
        hoverLine.style('opacity', 1);
      })
      .on('mousemove', (event, d) => {
        const xPos = x(d.date)! + x.bandwidth() / 2;
        hoverLine.attr('x1', xPos).attr('x2', xPos);
        tooltip
          .html(
            `<div class="font-bold mb-1">${d.date}</div>` +
              `<div>Cost: $${d.costUsd.toFixed(4)}</div>` +
              `<div>Tokens: ${d.tokens.toLocaleString()}</div>`,
          )
          .style('left', event.pageX + 15 + 'px')
          .style('top', event.pageY - 28 + 'px');
      })
      .on('mouseleave', () => {
        tooltip.style('opacity', 0);
        hoverLine.style('opacity', 0);
      });

    svg
      .append('g')
      .attr('transform', `translate(0,${height})`)
      .call(
        d3.axisBottom(x).tickFormat((d: string) => {
          const parseTime = d3.timeParse('%Y-%m-%d');
          const date = parseTime(d);
          if (!date) return d;
          const currentYear = new Date().getFullYear();
          if (date.getFullYear() === currentYear) {
            return d3.timeFormat('%b %d')(date);
          }
          return d3.timeFormat('%b %d, %Y')(date);
        }),
      )
      .selectAll('text')
      .style('fill', '#9ca3af');

    svg
      .append('g')
      .call(d3.axisLeft(y).tickFormat(d => `$${d}`))
      .selectAll('text')
      .style('fill', '#9ca3af');
  }
}
