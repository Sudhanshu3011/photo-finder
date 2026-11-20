# Makefile for Visual Search API & Velunara Web Frontend
SHELL := /bin/bash
COMPOSE := docker compose

.DEFAULT_GOAL := help

.PHONY: help up down restart build build-frontend build-backend logs logs-frontend logs-backend logs-workers ps status clean

help:
	@echo "Visual Search & Velunara Web Suite"
	@echo ""
	@echo "Usage:"
	@echo "  make up               Build and start all services (frontend + backend + workers) in background"
	@echo "  make down             Stop and remove all containers"
	@echo "  make restart          Restart all services"
	@echo "  make build            Build or rebuild all docker images"
	@echo "  make build-frontend   Build or rebuild only the frontend image"
	@echo "  make build-backend    Build or rebuild only the backend API image"
	@echo "  make logs             Stream real-time logs from all services"
	@echo "  make logs-frontend    Stream logs from frontend container"
	@echo "  make logs-backend     Stream logs from backend API container"
	@echo "  make logs-workers     Stream logs from Celery worker containers"
	@echo "  make ps               Display status of all managed containers"
	@echo "  make clean            Stop containers and remove orphans"
	@echo ""

up:
	@echo "Starting all services (frontend on port 3000, backend on port 7860)..."
	$(COMPOSE) up -d --build

down:
	@echo "Stopping all services..."
	$(COMPOSE) down

restart:
	@echo "Restarting all services..."
	$(COMPOSE) restart

build:
	@echo "Building all images..."
	$(COMPOSE) build

build-frontend:
	@echo "Building frontend image..."
	$(COMPOSE) build frontend

build-backend:
	@echo "Building backend API image..."
	$(COMPOSE) build api

logs:
	$(COMPOSE) logs -f

logs-frontend:
	$(COMPOSE) logs -f frontend

logs-backend:
	$(COMPOSE) logs -f api

logs-workers:
	$(COMPOSE) logs -f worker-ingest worker-inference worker-clustering

ps:
	$(COMPOSE) ps

status: ps

clean:
	@echo "Cleaning up containers and orphan resources..."
	$(COMPOSE) down --remove-orphans

