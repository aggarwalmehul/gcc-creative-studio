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

import {Injectable} from '@angular/core';
import {HttpClient, HttpErrorResponse} from '@angular/common/http';
import {Observable, throwError} from 'rxjs';
import {catchError} from 'rxjs/operators';
import {environment} from '../../../environments/environment';

export interface TokenUsageRowV2 {
  timestamp: string;
  platform: string;
  userEmail: string;
  model: string;
  tokensIn: number;
  tokensOut: number;
  total: number;
  costUsd: number;
}

export interface TokenUsageDailyPoint {
  date: string;
  tokens: number;
  costUsd: number;
}

export interface TokenUsageByModel {
  model: string;
  tokens: number;
  costUsd: number;
  calls: number;
}

export interface TokenUsageByUser {
  userEmail: string;
  tokens: number;
  costUsd: number;
  calls: number;
}

export interface TokenUsageSummary {
  totalTokens: number;
  totalCostUsd: number;
  totalCalls: number;
  daily: TokenUsageDailyPoint[];
  byModel: TokenUsageByModel[];
  byUser: TokenUsageByUser[];
}

export interface BillingUnitRow {
  platform: string;
  model: string;
  unitType: string;
  quantity: number;
  costUsd: number;
  calls: number;
}

export interface BillingUnitsSummary {
  totalCostUsd: number;
  rows: BillingUnitRow[];
}

@Injectable({
  providedIn: 'root',
})
export class TokenUsageService {
  private apiUrl = `${environment.backendURL}/admin/token-usage`;

  constructor(private http: HttpClient) {}

  // TOKEN_USAGE_DASHBOARD_V2: date-range-scoped raw rows, no row limit, each with cost.
  getTokenUsageV2(startDate: string, endDate: string): Observable<TokenUsageRowV2[]> {
    return this.http
      .get<TokenUsageRowV2[]>(
        `${this.apiUrl}/v2?start_date=${startDate}&end_date=${endDate}`,
      )
      .pipe(catchError(this.handleError));
  }

  getTokenUsageSummary(startDate: string, endDate: string): Observable<TokenUsageSummary> {
    return this.http
      .get<TokenUsageSummary>(
        `${this.apiUrl}/summary?start_date=${startDate}&end_date=${endDate}`,
      )
      .pipe(catchError(this.handleError));
  }

  getBillingUnitsSummary(startDate: string, endDate: string): Observable<BillingUnitsSummary> {
    return this.http
      .get<BillingUnitsSummary>(
        `${this.apiUrl}/billing-units?start_date=${startDate}&end_date=${endDate}`,
      )
      .pipe(catchError(this.handleError));
  }

  private handleError(error: HttpErrorResponse) {
    let errorMessage = 'An unknown error occurred!';
    if (error.error instanceof ErrorEvent) {
      errorMessage = `Error: ${error.error.message}`;
    } else {
      errorMessage = `Error Code: ${error.status}\nMessage: ${error.message}`;
      if (error.error && typeof error.error === 'object' && error.error.detail) {
        errorMessage += `\nDetails: ${JSON.stringify(error.error.detail)}`;
      } else if (error.error) {
        errorMessage += `\nBackend Error: ${JSON.stringify(error.error)}`;
      }
    }
    console.error(errorMessage);
    return throwError(() => new Error(errorMessage));
  }
}
