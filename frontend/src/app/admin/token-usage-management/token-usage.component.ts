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

import {Component, OnInit, AfterViewInit, ViewChild, ElementRef} from '@angular/core';
import {MatTableDataSource} from '@angular/material/table';
import {MatSnackBar} from '@angular/material/snack-bar';
import {forkJoin} from 'rxjs';
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
  ) {}

  ngOnInit(): void {
    this.loadAll();
  }

  ngAfterViewInit(): void {
    // Chart rendering (Stage 3) hooks in here once the view is ready.
  }

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
        // Stage 3 will call the D3 render function here.
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
}
