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

import {Component, OnInit} from '@angular/core';
import {MatTableDataSource} from '@angular/material/table';
import {MatSnackBar} from '@angular/material/snack-bar';
import {TokenUsageService, TokenUsageRow} from './token-usage.service';

@Component({
  selector: 'app-token-usage-management',
  templateUrl: './token-usage.component.html',
  styleUrls: ['./token-usage.component.scss'],
})
export class TokenUsageManagementComponent implements OnInit {
  dataSource = new MatTableDataSource<TokenUsageRow>();
  displayedColumns: string[] = [
    'timestamp',
    'platform',
    'userEmail',
    'model',
    'total',
  ];
  isLoading = false;
  days = 7;

  constructor(
    private tokenUsageService: TokenUsageService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.loadUsage();
  }

  loadUsage(): void {
    this.isLoading = true;
    this.tokenUsageService.getTokenUsage(this.days).subscribe({
      next: rows => {
        this.dataSource.data = rows;
        this.isLoading = false;
      },
      error: err => {
        console.error('Failed to load token usage', err);
        this.snackBar.open('Failed to load token usage', 'Close', {
          duration: 3000,
        });
        this.isLoading = false;
      },
    });
  }
}
