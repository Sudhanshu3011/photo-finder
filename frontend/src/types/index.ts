/**
 * VisualSearch — Domain TypeScript Models
 * Elementum Editorial Design System
 * 
 * Strict User-Centric Principle:
 * No technical jargon (RetinaFace, ArcFace, Celery, FAISS, CLIP) in user-facing types.
 */

export type UserRole = "Studio Owner" | "Studio Admin" | "Contributor" | "Viewer";

export interface User {
  id: string;
  name: string;
  email: string;
  avatarUrl: string;
}

export interface Workspace {
  id: string;
  name: string;
  subdomain: string;
  role: UserRole;
  photoCount: number;
  initials: string;
  themeColor: string; // pastel hex for avatar
  isCurrent: boolean;
}

export interface Album {
  id: string;
  title: string;
  description?: string;
  photoCount: number;
  peopleCount: number;
  coverUrl: string;
  updatedAt: string;
  isPrivate: boolean;
}

export interface DetectedFace {
  id: string;
  box: { x: number; y: number; width: number; height: number }; // percentage coordinates
  personName?: string;
  confidence: number;
}

export interface Photo {
  id: string;
  url: string;
  title: string;
  albumId: string;
  albumTitle: string;
  createdAt: string;
  detectedFaces?: DetectedFace[];
}

export interface Person {
  id: string;
  name: string;
  avatarUrl: string;
  photoCount: number;
  albumCount: number;
  candidPreviews: string[];
  isNamed: boolean;
}

export interface SearchMatch {
  photo: Photo;
  matchedFaceCropUrl?: string;
  matchGrade: "Exact Match" | "High Match" | "Similar";
  matchedPersonName?: string;
}

export type SearchMode = "face" | "scene";

export type SearchSensitivity = "broad" | "balanced" | "exact";

export interface BatchItem {
  id: string;
  file: File;
  previewUrl: string;
  name: string;
  sizeBytes: number;
  status: "queued" | "uploading" | "organizing" | "ready" | "error";
  progressPercent: number;
  peopleIdentified?: number;
}

export interface AlbumMemberAccess {
  userId: string;
  userName: string;
  userEmail: string;
  userAvatarUrl: string;
  studioRole: UserRole;
  canView: boolean;
  canAddPhotos: boolean;
  fullAccess: boolean;
}

