"""MySQL 建表 DDL（Phase 5D）。

从 SQLite schema 自动生成，供 MetadataStore.initialize() 和 migrate_to_mysql.py 共用。
"""

MYSQL_DDL = [
    """CREATE TABLE IF NOT EXISTS `bad_cases` (
  `id` int NOT NULL AUTO_INCREMENT,
  `trace_id` text COLLATE utf8mb4_unicode_ci,
  `question` text COLLATE utf8mb4_unicode_ci,
  `answer` text COLLATE utf8mb4_unicode_ci,
  `reason` text COLLATE utf8mb4_unicode_ci,
  `extra` text COLLATE utf8mb4_unicode_ci,
  `collected_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `connections` (
  `id` int NOT NULL AUTO_INCREMENT,
  `source_note_id` text COLLATE utf8mb4_unicode_ci,
  `target_note_id` text COLLATE utf8mb4_unicode_ci,
  `relation_type` text COLLATE utf8mb4_unicode_ci,
  `strength` double DEFAULT '0.5',
  `description` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  `is_ai_generated` int DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_connections_target` (`target_note_id`(255)),
  KEY `idx_connections_source` (`source_note_id`(255))
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `digest_reports` (
  `id` int NOT NULL AUTO_INCREMENT,
  `report_type` text COLLATE utf8mb4_unicode_ci,
  `report_date` text COLLATE utf8mb4_unicode_ci,
  `content` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `eval_runs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `run_type` text COLLATE utf8mb4_unicode_ci,
  `total` int DEFAULT NULL,
  `passed` int DEFAULT NULL,
  `pass_rate` double DEFAULT NULL,
  `avg_score` double DEFAULT NULL,
  `duration_ms` double DEFAULT NULL,
  `details` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `idx_eval_runs_created` (`created_at`(255))
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `eval_scores` (
  `id` int NOT NULL AUTO_INCREMENT,
  `trace_id` text COLLATE utf8mb4_unicode_ci,
  `question` text COLLATE utf8mb4_unicode_ci,
  `answer` text COLLATE utf8mb4_unicode_ci,
  `score` int DEFAULT NULL,
  `dimensions` text COLLATE utf8mb4_unicode_ci,
  `comment` text COLLATE utf8mb4_unicode_ci,
  `judged_at` text COLLATE utf8mb4_unicode_ci,
  `run_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_eval_scores_judged` (`judged_at`(255))
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `golden_cases` (
  `id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `question` text COLLATE utf8mb4_unicode_ci,
  `expected_keywords` text COLLATE utf8mb4_unicode_ci,
  `expected_sources` text COLLATE utf8mb4_unicode_ci,
  `min_score` double DEFAULT '0.7',
  `enabled` int DEFAULT '1',
  `created_at` text COLLATE utf8mb4_unicode_ci,
  `updated_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `ingestion_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `note_id` text COLLATE utf8mb4_unicode_ci,
  `event` text COLLATE utf8mb4_unicode_ci,
  `status` text COLLATE utf8mb4_unicode_ci,
  `message` text COLLATE utf8mb4_unicode_ci,
  `duration_ms` int DEFAULT NULL,
  `timestamp` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `knowledge_fragments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `session_id` text COLLATE utf8mb4_unicode_ci,
  `title` text COLLATE utf8mb4_unicode_ci,
  `content` text COLLATE utf8mb4_unicode_ci,
  `status` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `messages` (
  `id` int NOT NULL AUTO_INCREMENT,
  `session_id` text COLLATE utf8mb4_unicode_ci,
  `role` text COLLATE utf8mb4_unicode_ci,
  `content` text COLLATE utf8mb4_unicode_ci,
  `timeline` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `idx_messages_session` (`session_id`(255),`id`)
) ENGINE=InnoDB AUTO_INCREMENT=74 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `metrics` (
  `id` int NOT NULL AUTO_INCREMENT,
  `trace_id` text COLLATE utf8mb4_unicode_ci,
  `metric_type` text COLLATE utf8mb4_unicode_ci,
  `metric_name` text COLLATE utf8mb4_unicode_ci,
  `value` double DEFAULT NULL,
  `metadata` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `idx_metrics_trace` (`trace_id`(255)),
  KEY `idx_metrics_type_time` (`metric_type`(255),`created_at`(255))
) ENGINE=InnoDB AUTO_INCREMENT=168 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `usage_counters` (
  `period_type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `period_key` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tokens` int NOT NULL DEFAULT '0',
  `cost` double NOT NULL DEFAULT '0',
  `calls` int NOT NULL DEFAULT '0',
  `updated_at` text COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`period_type`,`period_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `note_tags` (
  `note_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tag_id` int NOT NULL,
  `confidence` double DEFAULT NULL,
  PRIMARY KEY (`note_id`,`tag_id`),
  KEY `idx_note_tags_note` (`note_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `notes` (
  `id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` text COLLATE utf8mb4_unicode_ci,
  `source_type` text COLLATE utf8mb4_unicode_ci,
  `source_path` text COLLATE utf8mb4_unicode_ci,
  `file_hash` text COLLATE utf8mb4_unicode_ci,
  `content_preview` text COLLATE utf8mb4_unicode_ci,
  `content_length` int DEFAULT '0',
  `chunk_count` int DEFAULT '0',
  `status` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  `updated_at` text COLLATE utf8mb4_unicode_ci,
  `ingested_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `idx_notes_created` (`created_at`(255)),
  KEY `idx_notes_status` (`status`(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `reviews` (
  `note_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ease_factor` double DEFAULT '2.5',
  `interval_days` int DEFAULT '0',
  `due_date` text COLLATE utf8mb4_unicode_ci,
  `review_count` int DEFAULT '0',
  `last_quality` int DEFAULT NULL,
  `last_reviewed_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`note_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `rss_entries` (
  `id` int NOT NULL AUTO_INCREMENT,
  `feed_id` int DEFAULT NULL,
  `entry_id` text COLLATE utf8mb4_unicode_ci,
  `title` text COLLATE utf8mb4_unicode_ci,
  `link` text COLLATE utf8mb4_unicode_ci,
  `note_id` text COLLATE utf8mb4_unicode_ci,
  `published_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `rss_feeds` (
  `id` int NOT NULL AUTO_INCREMENT,
  `url` text COLLATE utf8mb4_unicode_ci,
  `title` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  `last_fetched_at` text COLLATE utf8mb4_unicode_ci,
  `entry_count` int DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `sessions` (
  `id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  `updated_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `idx_sessions_updated` (`updated_at`(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `tags` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` text COLLATE utf8mb4_unicode_ci,
  `category` text COLLATE utf8mb4_unicode_ci,
  `is_ai_generated` int DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=27 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS `trace_events` (
  `id` int NOT NULL AUTO_INCREMENT,
  `trace_id` text COLLATE utf8mb4_unicode_ci,
  `seq` int DEFAULT NULL,
  `event_type` text COLLATE utf8mb4_unicode_ci,
  `name` text COLLATE utf8mb4_unicode_ci,
  `input` text COLLATE utf8mb4_unicode_ci,
  `output` text COLLATE utf8mb4_unicode_ci,
  `token_usage` text COLLATE utf8mb4_unicode_ci,
  `latency_ms` double DEFAULT NULL,
  `run_id` text COLLATE utf8mb4_unicode_ci,
  `created_at` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`),
  KEY `idx_trace_events_trace` (`trace_id`(255),`seq`)
) ENGINE=InnoDB AUTO_INCREMENT=675 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
]
