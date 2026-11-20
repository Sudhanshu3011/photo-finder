export const currentUser = {
  id: "usr_elena_01",
  name: "Elena Rostova",
  email: "elena@studioalpha.com",
  avatarUrl: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=200&q=80",
};

export const workspaces = [
  {
    id: "ws_alpha_01",
    name: "Studio Alpha Photography",
    subdomain: "alpha.visualsearch.io",
    role: "Studio Owner",
    photoCount: 14200,
    initials: "SA",
    themeColor: "#D8F3DC", // mint
    isCurrent: true,
  },
  {
    id: "ws_metropolis_02",
    name: "Metropolis Annual Gala 2026",
    subdomain: "metropolis.visualsearch.io",
    role: "Contributor",
    photoCount: 3400,
    initials: "MG",
    themeColor: "#FCE7F3", // rose
    isCurrent: false,
  },
  {
    id: "ws_apex_03",
    name: "Apex Media Agency",
    subdomain: "apex.visualsearch.io",
    role: "Viewer",
    photoCount: 8900,
    initials: "AM",
    themeColor: "#FEF3C7", // butter
    isCurrent: false,
  },
];

export const albums = [
  {
    id: "alb_gala_01",
    title: "VIP Gala Red Carpet",
    description: "Evening gala arrivals, step-and-repeat portraits, and celebrity guest photos.",
    photoCount: 420,
    peopleCount: 48,
    coverUrl: "https://images.unsplash.com/photo-1511578314322-379afb476865?auto=format&fit=crop&w=800&q=80",
    updatedAt: "2 hours ago",
    isPrivate: true,
  },
  {
    id: "alb_keynote_02",
    title: "Keynote Presentations",
    description: "Main stage keynote speakers, panel discussions, and audience reactions.",
    photoCount: 680,
    peopleCount: 32,
    coverUrl: "https://images.unsplash.com/photo-1475721027785-f74eccf877e2?auto=format&fit=crop&w=800&q=80",
    updatedAt: "Yesterday",
    isPrivate: false,
  },
  {
    id: "alb_summer_03",
    title: "Summer Creative Retreat",
    description: "Outdoor workshop sessions, collaborative sprints, and candid gatherings.",
    photoCount: 290,
    peopleCount: 24,
    coverUrl: "https://images.unsplash.com/photo-1528605248644-14dd04022da1?auto=format&fit=crop&w=800&q=80",
    updatedAt: "3 days ago",
    isPrivate: false,
  },
];

export const people = [
  {
    id: "per_marcus_01",
    name: "Marcus Chen",
    avatarUrl: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=400&q=80",
    photoCount: 148,
    albumCount: 3,
    candidPreviews: [
      "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=150&q=80",
      "https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?auto=format&fit=crop&w=150&q=80",
      "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=150&q=80",
    ],
    isNamed: true,
  },
  {
    id: "per_sarah_02",
    name: "Sarah Jenkins",
    avatarUrl: "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=400&q=80",
    photoCount: 94,
    albumCount: 2,
    candidPreviews: [
      "https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&w=150&q=80",
      "https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=150&q=80",
    ],
    isNamed: true,
  },
  {
    id: "per_david_03",
    name: "David Miller",
    avatarUrl: "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?auto=format&fit=crop&w=400&q=80",
    photoCount: 62,
    albumCount: 2,
    candidPreviews: [
      "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?auto=format&fit=crop&w=150&q=80",
    ],
    isNamed: true,
  },
  {
    id: "per_amara_04",
    name: "Amara Thorne",
    avatarUrl: "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?auto=format&fit=crop&w=400&q=80",
    photoCount: 81,
    albumCount: 3,
    candidPreviews: [
      "https://images.unsplash.com/photo-1580489944761-15a19d654956?auto=format&fit=crop&w=150&q=80",
    ],
    isNamed: true,
  },
  {
    id: "per_unnamed_05",
    name: "Familiar Guest #14",
    avatarUrl: "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?auto=format&fit=crop&w=400&q=80",
    photoCount: 28,
    albumCount: 1,
    candidPreviews: [
      "https://images.unsplash.com/photo-1501196354995-cbb51c65aaea?auto=format&fit=crop&w=150&q=80",
    ],
    isNamed: false,
  },
];

export const samplePhotos = [
  {
    id: "pho_01",
    url: "https://images.unsplash.com/photo-1511578314322-379afb476865?auto=format&fit=crop&w=800&q=80",
    title: "Gala Stage Opening Moment",
    albumId: "alb_gala_01",
    albumTitle: "VIP Gala Red Carpet",
    createdAt: "Oct 19, 2026",
  },
  {
    id: "pho_02",
    url: "https://images.unsplash.com/photo-1522071820081-009f0129c71c?auto=format&fit=crop&w=800&q=80",
    title: "Leadership Panel Collaboration",
    albumId: "alb_keynote_02",
    albumTitle: "Keynote Presentations",
    createdAt: "Oct 18, 2026",
  },
  {
    id: "pho_03",
    url: "https://images.unsplash.com/photo-1528605248644-14dd04022da1?auto=format&fit=crop&w=800&q=80",
    title: "Outdoor Coffee & Brainstorming",
    albumId: "alb_summer_03",
    albumTitle: "Summer Creative Retreat",
    createdAt: "Oct 16, 2026",
  },
  {
    id: "pho_04",
    url: "https://images.unsplash.com/photo-1515187029135-18ee286d815b?auto=format&fit=crop&w=800&q=80",
    title: "Evening Awards Ceremony Banquet",
    albumId: "alb_gala_01",
    albumTitle: "VIP Gala Red Carpet",
    createdAt: "Oct 19, 2026",
  },
];

export const sampleMemberPermissions = [
  {
    userId: "usr_devon_02",
    userName: "Devon Lane",
    userEmail: "devon@studioalpha.com",
    userAvatarUrl: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=150&q=80",
    studioRole: "Studio Admin",
    canView: true,
    canAddPhotos: true,
    fullAccess: true,
  },
  {
    userId: "usr_amara_03",
    userName: "Amara Thorne",
    userEmail: "amara@partneragency.com",
    userAvatarUrl: "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?auto=format&fit=crop&w=150&q=80",
    studioRole: "Contributor",
    canView: true,
    canAddPhotos: true,
    fullAccess: false,
  },
  {
    userId: "usr_guest_04",
    userName: "Guest Event Coordinator",
    userEmail: "guest@metropolisgala.org",
    userAvatarUrl: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80",
    studioRole: "Viewer",
    canView: true,
    canAddPhotos: false,
    fullAccess: false,
  },
];

