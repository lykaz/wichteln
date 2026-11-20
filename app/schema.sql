CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    sub TEXT UNIQUE NOT NULL,
    email TEXT,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    drawn_at TEXT
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER NOT NULL REFERENCES groups(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (group_id, user_id)
);

CREATE TABLE IF NOT EXISTS exclusions (
    group_id INTEGER NOT NULL REFERENCES groups(id),
    user_id_a INTEGER NOT NULL REFERENCES users(id),
    user_id_b INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (group_id, user_id_a, user_id_b)
);

CREATE TABLE IF NOT EXISTS wishlist_items (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
    group_id INTEGER NOT NULL REFERENCES groups(id),
    giver_id INTEGER NOT NULL REFERENCES users(id),
    receiver_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (group_id, giver_id)
);
