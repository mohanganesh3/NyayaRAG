#!/usr/bin/env python3
# /// script
# dependencies = [
#   "psycopg[binary]",
#   "rich",
# ]
# ///

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import psycopg
from rich.console import Console
from rich.table import Table

# Configuration
DATABASE_URL = "postgresql://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"

console = Console()

def run_audit():
    console.print("[bold blue]NyayaRAG Backend Audit (12.63M Target)[/bold blue]\n")
    
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # 1. Total Document Counts
                cur.execute("SELECT COUNT(*) FROM legal_documents")
                doc_count = cur.fetchone()[0]
                
                cur.execute("SELECT COUNT(*) FROM document_chunks")
                chunk_count = cur.fetchone()[0]
                
                # 2. Citation Integrity
                cur.execute("SELECT COUNT(*) FROM citation_edges")
                edge_count = cur.fetchone()[0]
                
                # 3. Vectorization Status
                cur.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding_id IS NOT NULL")
                embedded_count = cur.fetchone()[0]
                
                # 4. Temporal Validity Distribution
                cur.execute("SELECT current_validity, COUNT(*) FROM document_chunks GROUP BY current_validity")
                validity_stats = cur.fetchall()
                
                # Render Results
                table = Table(title="System Summary")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="magenta")
                table.add_column("Status", style="green")
                
                target_docs = 12631044
                doc_status = "✅ COMPLETE" if doc_count >= target_docs else "❌ INCOMPLETE"
                table.add_row("Total Legal Documents", f"{doc_count:,}", doc_status)
                table.add_row("Total Document Chunks", f"{chunk_count:,}", "-")
                table.add_row("Citation Edges", f"{edge_count:,}", "-")
                
                vector_status = "✅ 100%" if embedded_count == chunk_count and chunk_count > 0 else "🏗️ PROCESSING"
                table.add_row("Embedded Chunks", f"{embedded_count:,}", vector_status)
                
                console.print(table)
                
                val_table = Table(title="Validity Distribution")
                val_table.add_column("Status", style="yellow")
                val_table.add_column("Count", style="white")
                for status, count in validity_stats:
                    val_table.add_row(str(status), f"{count:,}")
                console.print(val_table)

    except Exception as e:
        console.print(f"[bold red]Audit Failed:[/bold red] {e}")

if __name__ == "__main__":
    run_audit()
