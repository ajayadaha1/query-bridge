-- Chinook Database — PostgreSQL version
-- Classic sample database: digital music store
-- Source: https://github.com/lerocha/chinook-database (MIT License)

CREATE TABLE artist (
    artist_id SERIAL PRIMARY KEY,
    name VARCHAR(120)
);

CREATE TABLE album (
    album_id SERIAL PRIMARY KEY,
    title VARCHAR(160) NOT NULL,
    artist_id INTEGER NOT NULL REFERENCES artist(artist_id)
);

CREATE TABLE media_type (
    media_type_id SERIAL PRIMARY KEY,
    name VARCHAR(120)
);

CREATE TABLE genre (
    genre_id SERIAL PRIMARY KEY,
    name VARCHAR(120)
);

CREATE TABLE track (
    track_id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    album_id INTEGER REFERENCES album(album_id),
    media_type_id INTEGER NOT NULL REFERENCES media_type(media_type_id),
    genre_id INTEGER REFERENCES genre(genre_id),
    composer VARCHAR(220),
    milliseconds INTEGER NOT NULL,
    bytes INTEGER,
    unit_price NUMERIC(10,2) NOT NULL
);

CREATE TABLE employee (
    employee_id SERIAL PRIMARY KEY,
    last_name VARCHAR(20) NOT NULL,
    first_name VARCHAR(20) NOT NULL,
    title VARCHAR(30),
    reports_to INTEGER REFERENCES employee(employee_id),
    birth_date TIMESTAMP,
    hire_date TIMESTAMP,
    address VARCHAR(70),
    city VARCHAR(40),
    state VARCHAR(40),
    country VARCHAR(40),
    postal_code VARCHAR(10),
    phone VARCHAR(24),
    fax VARCHAR(24),
    email VARCHAR(60)
);

CREATE TABLE customer (
    customer_id SERIAL PRIMARY KEY,
    first_name VARCHAR(40) NOT NULL,
    last_name VARCHAR(20) NOT NULL,
    company VARCHAR(80),
    address VARCHAR(70),
    city VARCHAR(40),
    state VARCHAR(40),
    country VARCHAR(40),
    postal_code VARCHAR(10),
    phone VARCHAR(24),
    fax VARCHAR(24),
    email VARCHAR(60) NOT NULL,
    support_rep_id INTEGER REFERENCES employee(employee_id)
);

CREATE TABLE invoice (
    invoice_id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customer(customer_id),
    invoice_date TIMESTAMP NOT NULL,
    billing_address VARCHAR(70),
    billing_city VARCHAR(40),
    billing_state VARCHAR(40),
    billing_country VARCHAR(40),
    billing_postal_code VARCHAR(10),
    total NUMERIC(10,2) NOT NULL
);

CREATE TABLE invoice_line (
    invoice_line_id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(invoice_id),
    track_id INTEGER NOT NULL REFERENCES track(track_id),
    unit_price NUMERIC(10,2) NOT NULL,
    quantity INTEGER NOT NULL
);

CREATE TABLE playlist (
    playlist_id SERIAL PRIMARY KEY,
    name VARCHAR(120)
);

CREATE TABLE playlist_track (
    playlist_id INTEGER NOT NULL REFERENCES playlist(playlist_id),
    track_id INTEGER NOT NULL REFERENCES track(track_id),
    PRIMARY KEY (playlist_id, track_id)
);

-- ─── Seed Data ───────────────────────────────────────────────────────

INSERT INTO media_type (name) VALUES
('MPEG audio file'), ('Protected AAC audio file'), ('Protected MPEG-4 video file'),
('Purchased AAC audio file'), ('AAC audio file');

INSERT INTO genre (name) VALUES
('Rock'), ('Jazz'), ('Metal'), ('Alternative & Punk'), ('Rock And Roll'),
('Blues'), ('Latin'), ('Reggae'), ('Pop'), ('Soundtrack'),
('Bossa Nova'), ('Easy Listening'), ('Heavy Metal'), ('R&B/Soul'), ('Electronica/Dance'),
('World'), ('Hip Hop/Rap'), ('Science Fiction'), ('TV Shows'), ('Sci Fi & Fantasy'),
('Drama'), ('Comedy'), ('Alternative'), ('Classical'), ('Opera');

INSERT INTO artist (name) VALUES
('AC/DC'), ('Accept'), ('Aerosmith'), ('Alanis Morissette'), ('Alice In Chains'),
('Antônio Carlos Jobim'), ('Apocalyptica'), ('Audioslave'), ('BackBeat'), ('Billy Cobham'),
('Black Label Society'), ('Black Sabbath'), ('Body Count'), ('Bruce Dickinson'), ('Buddy Guy'),
('Caetano Veloso'), ('Chico Buarque'), ('Chico Science & Nação Zumbi'), ('Cidade Negra'), ('Claudio Zoli'),
('Led Zeppelin'), ('Frank Zappa & Captain Beefheart'), ('Marcos Valle'), ('Milton Nascimento'), ('Ozzy Osbourne'),
('U2'), ('Jimi Hendrix'), ('Metallica'), ('Queen'), ('The Rolling Stones'),
('Pearl Jam'), ('Nirvana'), ('Red Hot Chili Peppers'), ('R.E.M.'), ('Foo Fighters'),
('Iron Maiden'), ('Deep Purple'), ('Eric Clapton'), ('Stevie Ray Vaughan'), ('B.B. King'),
('John Mayer'), ('Coldplay'), ('Radiohead'), ('The Beatles'), ('Pink Floyd'),
('Eagles'), ('Fleetwood Mac'), ('David Bowie'), ('The Who'), ('Cream');

INSERT INTO album (title, artist_id) VALUES
('For Those About to Rock We Salute You', 1), ('Balls to the Wall', 2),
('Restless and Wild', 2), ('Let There Be Rock', 1),
('Big Ones', 3), ('Jagged Little Pill', 4),
('Facelift', 5), ('Warner 25 Anos', 6),
('Plays Metallica By Four Cellos', 7), ('Audioslave', 8),
('Out of Exile', 8), ('BackBeat Soundtrack', 9),
('The Best Of Billy Cobham', 10), ('Alcohol Fueled Brewtality', 11),
('Black Sabbath', 12), ('Black Sabbath Vol. 4', 12),
('Body Count', 13), ('Chemical Wedding', 14),
('The Best Of Buddy Guy', 15), ('Prenda Minha', 16),
('Led Zeppelin IV', 21), ('Houses of the Holy', 21),
('Physical Graffiti', 21), ('Hot Rocks', 30),
('Sticky Fingers', 30), ('Ten', 31),
('Vs.', 31), ('Nevermind', 32),
('In Utero', 32), ('Californication', 33),
('Blood Sugar Sex Magik', 33), ('Automatic for the People', 34),
('The Colour and the Shape', 35), ('Iron Maiden', 36),
('The Number of the Beast', 36), ('Machine Head', 37),
('Unplugged', 38), ('Texas Flood', 39),
('Live at the Regal', 40), ('Continuum', 41),
('A Rush of Blood to the Head', 42), ('OK Computer', 43),
('Abbey Road', 44), ('The Dark Side of the Moon', 45),
('Hotel California', 46), ('Rumours', 47),
('The Rise and Fall of Ziggy Stardust', 48), ('Who''s Next', 49),
('Disraeli Gears', 50), ('Master of Puppets', 28);

INSERT INTO track (name, album_id, media_type_id, genre_id, composer, milliseconds, bytes, unit_price) VALUES
('For Those About to Rock', 1, 1, 1, 'Angus Young, Malcolm Young, Brian Johnson', 343719, 11170334, 0.99),
('Put The Finger On You', 1, 1, 1, 'Angus Young, Malcolm Young, Brian Johnson', 205662, 6713451, 0.99),
('Balls to the Wall', 2, 1, 1, NULL, 342562, 5510424, 0.99),
('Restless and Wild', 3, 1, 1, 'F. Baltes, S. Kaufman, U.D. Weil, R.A.S Borch', 252051, 4331779, 0.99),
('Big Gun', 4, 1, 1, 'Angus Young, Malcolm Young, Brian Johnson', 213054, 6990000, 0.99),
('Walk On Water', 5, 1, 1, 'Steven Tyler, Joe Perry, Jack Blades, Tommy Shaw', 295680, 9700000, 0.99),
('Love In An Elevator', 5, 1, 1, 'Steven Tyler, Joe Perry', 321828, 10500000, 0.99),
('You Oughta Know', 6, 1, 1, 'Alanis Morissette, Glen Ballard', 249234, 8100000, 0.99),
('Man In The Box', 7, 1, 1, 'Jerry Cantrell', 286641, 9300000, 0.99),
('Desafinado', 8, 1, 2, NULL, 185338, 5990000, 0.99),
('Enter Sandman', 50, 1, 3, 'James Hetfield, Lars Ulrich, Kirk Hammett', 331560, 10800000, 0.99),
('Master of Puppets', 50, 1, 3, 'James Hetfield, Lars Ulrich, Kirk Hammett, Cliff Burton', 515539, 16800000, 0.99),
('Stairway to Heaven', 21, 1, 1, 'Jimmy Page, Robert Plant', 482130, 15700000, 0.99),
('Black Dog', 21, 1, 1, 'Jimmy Page, Robert Plant, John Paul Jones', 296672, 9600000, 0.99),
('Whole Lotta Love', 21, 1, 1, 'Jimmy Page, Robert Plant, John Paul Jones, John Bonham', 334471, 10900000, 0.99),
('Satisfaction', 24, 1, 1, 'Mick Jagger, Keith Richards', 225955, 7300000, 0.99),
('Brown Sugar', 25, 1, 1, 'Mick Jagger, Keith Richards', 228661, 7400000, 0.99),
('Alive', 26, 1, 4, 'Eddie Vedder', 341163, 11100000, 0.99),
('Jeremy', 26, 1, 4, 'Eddie Vedder, Jeff Ament', 318981, 10400000, 0.99),
('Smells Like Teen Spirit', 28, 1, 4, 'Kurt Cobain, Dave Grohl, Krist Novoselic', 301132, 9800000, 0.99),
('Come As You Are', 28, 1, 4, 'Kurt Cobain', 219219, 7100000, 0.99),
('Lithium', 28, 1, 4, 'Kurt Cobain', 253988, 8300000, 0.99),
('Under the Bridge', 30, 1, 4, 'Anthony Kiedis, Flea, John Frusciante, Chad Smith', 264359, 8600000, 0.99),
('Give It Away', 31, 1, 4, 'Anthony Kiedis, Flea, John Frusciante, Chad Smith', 283960, 9200000, 0.99),
('Losing My Religion', 32, 1, 4, 'Bill Berry, Peter Buck, Mike Mills, Michael Stipe', 269557, 8800000, 0.99),
('Everlong', 33, 1, 4, 'Dave Grohl', 250749, 8200000, 0.99),
('The Trooper', 35, 1, 3, 'Steve Harris', 250853, 8200000, 0.99),
('Run to the Hills', 35, 1, 3, 'Steve Harris', 229666, 7500000, 0.99),
('Smoke on the Water', 36, 1, 1, 'Ritchie Blackmore, Ian Gillan, Roger Glover, Jon Lord, Ian Paice', 338493, 11000000, 0.99),
('Layla', 37, 1, 1, 'Eric Clapton, Jim Gordon', 437568, 14300000, 0.99),
('Pride and Joy', 38, 1, 1, 'Stevie Ray Vaughan', 215307, 7000000, 0.99),
('The Thrill Is Gone', 39, 1, 2, 'Roy Hawkins, Rick Darnell', 336356, 10900000, 0.99),
('Gravity', 40, 1, 1, 'John Mayer', 254511, 8300000, 0.99),
('Waiting on the World to Change', 40, 1, 1, 'John Mayer', 199081, 6500000, 0.99),
('The Scientist', 41, 1, 4, 'Guy Berryman, Chris Martin, Jon Buckland, Will Champion', 309263, 10100000, 0.99),
('Clocks', 41, 1, 4, 'Guy Berryman, Chris Martin, Jon Buckland, Will Champion', 307499, 10000000, 0.99),
('Paranoid Android', 42, 1, 4, 'Thom Yorke, Jonny Greenwood, Colin Greenwood, Ed OBrien, Phil Selway', 383853, 12500000, 0.99),
('Karma Police', 42, 1, 4, 'Thom Yorke, Jonny Greenwood, Colin Greenwood, Ed OBrien, Phil Selway', 264396, 8600000, 0.99),
('Come Together', 43, 1, 1, 'John Lennon, Paul McCartney', 259947, 8500000, 0.99),
('Here Comes The Sun', 43, 1, 1, 'George Harrison', 185338, 6000000, 0.99),
('Money', 44, 1, 1, 'Roger Waters', 382305, 12400000, 0.99),
('Comfortably Numb', 44, 1, 1, 'David Gilmour, Roger Waters', 382296, 12400000, 0.99),
('Hotel California', 45, 1, 1, 'Don Felder, Don Henley, Glenn Frey', 391794, 12800000, 0.99),
('Go Your Own Way', 46, 1, 1, 'Lindsey Buckingham', 232029, 7500000, 0.99),
('Dreams', 46, 1, 1, 'Stevie Nicks', 257800, 8400000, 0.99),
('Starman', 47, 1, 1, 'David Bowie', 256902, 8400000, 0.99),
('Baba ORiley', 48, 1, 1, 'Pete Townshend', 309263, 10100000, 0.99),
('Sunshine of Your Love', 49, 1, 1, 'Jack Bruce, Pete Brown, Eric Clapton', 252891, 8200000, 0.99);

-- Employees
INSERT INTO employee (last_name, first_name, title, reports_to, birth_date, hire_date, address, city, state, country, postal_code, phone, email) VALUES
('Adams', 'Andrew', 'General Manager', NULL, '1962-02-18', '2002-08-14', '11120 Jasper Ave NW', 'Edmonton', 'AB', 'Canada', 'T5K 2N1', '+1 780 428-9482', 'andrew@chinook.com'),
('Edwards', 'Nancy', 'Sales Manager', 1, '1958-12-08', '2002-05-01', '825 8 Ave SW', 'Calgary', 'AB', 'Canada', 'T2P 2T3', '+1 403 262-3443', 'nancy@chinook.com'),
('Peacock', 'Jane', 'Sales Support Agent', 2, '1973-08-29', '2002-04-01', '1111 6 Ave SW', 'Calgary', 'AB', 'Canada', 'T2P 5M5', '+1 403 262-3443', 'jane@chinook.com'),
('Park', 'Margaret', 'Sales Support Agent', 2, '1947-09-19', '2003-05-03', '683 10 Street SW', 'Calgary', 'AB', 'Canada', 'T2P 5G3', '+1 403 263-4423', 'margaret@chinook.com'),
('Johnson', 'Steve', 'Sales Support Agent', 2, '1965-03-03', '2003-10-17', '7727B 41 Ave', 'Calgary', 'AB', 'Canada', 'T3B 1Y7', '+1 403 262-3443', 'steve@chinook.com'),
('Mitchell', 'Michael', 'IT Manager', 1, '1973-07-01', '2003-10-17', '5827 Bowness Road NW', 'Calgary', 'AB', 'Canada', 'T3B 0C5', '+1 403 246-9887', 'michael@chinook.com'),
('King', 'Robert', 'IT Staff', 6, '1970-05-29', '2004-01-02', '590 Columbia Blvd West', 'Lethbridge', 'AB', 'Canada', 'T1K 5N8', '+1 403 456-9986', 'robert@chinook.com'),
('Callahan', 'Laura', 'IT Staff', 6, '1968-01-09', '2004-03-04', '923 7 ST NW', 'Lethbridge', 'AB', 'Canada', 'T1H 1Y8', '+1 403 467-3351', 'laura@chinook.com');

-- Customers (sample — 20 customers across multiple countries)
INSERT INTO customer (first_name, last_name, company, address, city, state, country, postal_code, phone, email, support_rep_id) VALUES
('Luís', 'Gonçalves', 'Embraer', 'Av. Brigadeiro Faria Lima, 2170', 'São José dos Campos', 'SP', 'Brazil', '12227-000', '+55 12 3923-5555', 'luisg@embraer.com.br', 3),
('Leonie', 'Köhler', NULL, 'Theodor-Heuss-Straße 34', 'Stuttgart', NULL, 'Germany', '70174', '+49 0711 2842222', 'leonekohler@surfeu.de', 5),
('François', 'Tremblay', NULL, '1498 rue Bélanger', 'Montréal', 'QC', 'Canada', 'H2G 1A7', '+1 514 721-4711', 'ftremblay@gmail.com', 3),
('Bjørn', 'Hansen', NULL, 'Ullevålsveien 14', 'Oslo', NULL, 'Norway', '0171', '+47 22 44 22 22', 'bjorn.hansen@yahoo.no', 4),
('František', 'Wichterlová', 'JetBrains s.r.o.', 'Klanova 9/506', 'Prague', NULL, 'Czech Republic', '14700', '+420 2 4172 5555', 'frantisek.wichterlova@jetbrains.com', 4),
('Helena', 'Holý', NULL, 'Rilská 3174/1', 'Prague', NULL, 'Czech Republic', '14300', '+420 2 4177 0449', 'hholy@gmail.com', 5),
('Astrid', 'Gruber', NULL, 'Rotenturmstraße 4, 1010 Innere Stadt', 'Vienna', NULL, 'Austria', '1010', '+43 01 5134505', 'astrid.gruber@apple.at', 5),
('Daan', 'Peeters', NULL, 'Grétrystraat 63', 'Brussels', NULL, 'Belgium', '1000', '+32 02 219 03 03', 'daan_peeters@apple.be', 4),
('Kara', 'Nielsen', NULL, 'Sønder Boulevard 51', 'Copenhagen', NULL, 'Denmark', '1720', '+45 31 20 15 05', 'kara.nielsen@jubii.dk', 4),
('Eduardo', 'Martins', 'Woodstock Discos', 'Rua Dr. Falcão Filho, 155', 'São Paulo', 'SP', 'Brazil', '01007-010', '+55 11 3033-5446', 'eduardo@woodstock.com.br', 4),
('Mark', 'Philips', 'Telus', '8210 111 ST NW', 'Edmonton', 'AB', 'Canada', 'T6G 2C7', '+1 780 434-4554', 'mphilips12@shaw.ca', 5),
('Jennifer', 'Peterson', NULL, '700 W Pender Street', 'Vancouver', 'BC', 'Canada', 'V6C 1G8', '+1 604 688-2255', 'jenniferp@rogers.ca', 3),
('Robert', 'Brown', NULL, '796 Dundas Street West', 'Toronto', 'ON', 'Canada', 'M6J 1V1', '+1 416 363-8888', 'robbrown@shaw.ca', 3),
('Frank', 'Harris', NULL, '1600 Amphitheatre Parkway', 'Mountain View', 'CA', 'USA', '94043-1351', '+1 650 253-0000', 'fharris@google.com', 4),
('Jack', 'Smith', NULL, '1 Microsoft Way', 'Redmond', 'WA', 'USA', '98052-8300', '+1 425 882-8080', 'jacksmith@microsoft.com', 5),
('Michelle', 'Brooks', NULL, '627 Broadway', 'New York', 'NY', 'USA', '10012-2612', '+1 212 221-3546', 'michelleb@aol.com', 3),
('Tim', 'Goyer', 'Apple Inc.', '1 Infinite Loop', 'Cupertino', 'CA', 'USA', '95014', '+1 408 996-1010', 'tgoyer@apple.com', 3),
('Dan', 'Miller', NULL, '541 Del Medio Avenue', 'Mountain View', 'CA', 'USA', '94040-111', '+1 650 644-3358', 'dmiller@comcast.com', 4),
('Manoj', 'Pareek', NULL, '12,Community Centre', 'Delhi', NULL, 'India', '110017', '+91 0124 39-5765', 'maaborber@yahoo.in', 3),
('Phil', 'Hughes', NULL, '113 Villawood Avenue', 'Villawood', 'NSW', 'Australia', '2163', '+61 02 9756-0723', 'phil.hughes@gmail.com', 3);

-- Invoices (sample — 25 invoices spanning 2009-2013)
INSERT INTO invoice (customer_id, invoice_date, billing_address, billing_city, billing_state, billing_country, billing_postal_code, total) VALUES
(1, '2009-01-01', 'Av. Brigadeiro Faria Lima, 2170', 'São José dos Campos', 'SP', 'Brazil', '12227-000', 3.98),
(2, '2009-01-02', 'Theodor-Heuss-Straße 34', 'Stuttgart', NULL, 'Germany', '70174', 3.96),
(3, '2009-01-03', '1498 rue Bélanger', 'Montréal', 'QC', 'Canada', 'H2G 1A7', 5.94),
(4, '2009-02-01', 'Ullevålsveien 14', 'Oslo', NULL, 'Norway', '0171', 8.91),
(5, '2009-03-04', 'Klanova 9/506', 'Prague', NULL, 'Czech Republic', '14700', 13.86),
(14, '2009-03-11', '1600 Amphitheatre Parkway', 'Mountain View', 'CA', 'USA', '94043-1351', 8.91),
(15, '2009-04-06', '1 Microsoft Way', 'Redmond', 'WA', 'USA', '98052-8300', 1.98),
(16, '2009-04-09', '627 Broadway', 'New York', 'NY', 'USA', '10012-2612', 3.96),
(1, '2010-01-18', 'Av. Brigadeiro Faria Lima, 2170', 'São José dos Campos', 'SP', 'Brazil', '12227-000', 13.86),
(10, '2010-03-16', 'Rua Dr. Falcão Filho, 155', 'São Paulo', 'SP', 'Brazil', '01007-010', 8.91),
(11, '2010-06-13', '8210 111 ST NW', 'Edmonton', 'AB', 'Canada', 'T6G 2C7', 1.98),
(12, '2010-09-13', '700 W Pender Street', 'Vancouver', 'BC', 'Canada', 'V6C 1G8', 5.94),
(17, '2010-12-02', '1 Infinite Loop', 'Cupertino', 'CA', 'USA', '95014', 1.98),
(18, '2011-01-15', '541 Del Medio Avenue', 'Mountain View', 'CA', 'USA', '94040-111', 3.96),
(6, '2011-05-19', 'Rilská 3174/1', 'Prague', NULL, 'Czech Republic', '14300', 5.94),
(7, '2011-07-06', 'Rotenturmstraße 4', 'Vienna', NULL, 'Austria', '1010', 8.91),
(8, '2011-10-14', 'Grétrystraat 63', 'Brussels', NULL, 'Belgium', '1000', 1.98),
(9, '2012-01-27', 'Sønder Boulevard 51', 'Copenhagen', NULL, 'Denmark', '1720', 3.98),
(13, '2012-04-26', '796 Dundas Street West', 'Toronto', 'ON', 'Canada', 'M6J 1V1', 1.98),
(19, '2012-07-31', '12,Community Centre', 'Delhi', NULL, 'India', '110017', 8.91),
(20, '2012-09-28', '113 Villawood Avenue', 'Villawood', 'NSW', 'Australia', '2163', 1.98),
(2, '2012-11-15', 'Theodor-Heuss-Straße 34', 'Stuttgart', NULL, 'Germany', '70174', 13.86),
(14, '2013-03-18', '1600 Amphitheatre Parkway', 'Mountain View', 'CA', 'USA', '94043-1351', 5.94),
(15, '2013-06-03', '1 Microsoft Way', 'Redmond', 'WA', 'USA', '98052-8300', 8.91),
(16, '2013-08-12', '627 Broadway', 'New York', 'NY', 'USA', '10012-2612', 1.98);

-- Invoice lines (linking invoices to tracks)
INSERT INTO invoice_line (invoice_id, track_id, unit_price, quantity) VALUES
(1, 1, 0.99, 1), (1, 2, 0.99, 1), (1, 3, 0.99, 1), (1, 4, 0.99, 1),
(2, 5, 0.99, 1), (2, 6, 0.99, 1), (2, 7, 0.99, 1), (2, 8, 0.99, 1),
(3, 9, 0.99, 1), (3, 10, 0.99, 1), (3, 11, 0.99, 1), (3, 12, 0.99, 1), (3, 13, 0.99, 1), (3, 14, 0.99, 1),
(4, 15, 0.99, 1), (4, 16, 0.99, 1), (4, 17, 0.99, 1), (4, 18, 0.99, 2), (4, 19, 0.99, 2), (4, 20, 0.99, 2),
(5, 21, 0.99, 2), (5, 22, 0.99, 2), (5, 23, 0.99, 2), (5, 24, 0.99, 2), (5, 25, 0.99, 2), (5, 26, 0.99, 2), (5, 27, 0.99, 2),
(6, 28, 0.99, 2), (6, 29, 0.99, 2), (6, 30, 0.99, 1), (6, 31, 0.99, 1), (6, 32, 0.99, 1), (6, 33, 0.99, 2),
(7, 34, 0.99, 1), (7, 35, 0.99, 1),
(8, 36, 0.99, 1), (8, 37, 0.99, 1), (8, 38, 0.99, 1), (8, 39, 0.99, 1),
(9, 40, 0.99, 2), (9, 41, 0.99, 2), (9, 42, 0.99, 2), (9, 43, 0.99, 2), (9, 44, 0.99, 2), (9, 45, 0.99, 2), (9, 46, 0.99, 2),
(10, 1, 0.99, 2), (10, 5, 0.99, 2), (10, 11, 0.99, 2), (10, 15, 0.99, 1), (10, 20, 0.99, 1),
(11, 25, 0.99, 1), (11, 30, 0.99, 1),
(12, 35, 0.99, 1), (12, 36, 0.99, 1), (12, 37, 0.99, 1), (12, 38, 0.99, 1), (12, 39, 0.99, 1), (12, 40, 0.99, 1),
(13, 2, 0.99, 1), (13, 4, 0.99, 1),
(14, 6, 0.99, 1), (14, 8, 0.99, 1), (14, 10, 0.99, 1), (14, 12, 0.99, 1),
(15, 14, 0.99, 1), (15, 16, 0.99, 1), (15, 18, 0.99, 1), (15, 20, 0.99, 1), (15, 22, 0.99, 1), (15, 24, 0.99, 1),
(16, 26, 0.99, 2), (16, 28, 0.99, 2), (16, 30, 0.99, 1), (16, 32, 0.99, 2), (16, 34, 0.99, 2),
(17, 1, 0.99, 1), (17, 3, 0.99, 1),
(18, 5, 0.99, 1), (18, 7, 0.99, 1), (18, 9, 0.99, 1), (18, 11, 0.99, 1),
(19, 13, 0.99, 1), (19, 15, 0.99, 1),
(20, 17, 0.99, 2), (20, 19, 0.99, 2), (20, 21, 0.99, 1), (20, 23, 0.99, 1), (20, 25, 0.99, 1), (20, 27, 0.99, 2),
(21, 29, 0.99, 1), (21, 31, 0.99, 1),
(22, 33, 0.99, 2), (22, 35, 0.99, 2), (22, 37, 0.99, 2), (22, 39, 0.99, 2), (22, 41, 0.99, 1), (22, 43, 0.99, 2), (22, 45, 0.99, 2),
(23, 2, 0.99, 1), (23, 4, 0.99, 1), (23, 6, 0.99, 1), (23, 8, 0.99, 1), (23, 10, 0.99, 1), (23, 12, 0.99, 1),
(24, 14, 0.99, 2), (24, 16, 0.99, 2), (24, 18, 0.99, 2), (24, 20, 0.99, 1), (24, 22, 0.99, 1), (24, 24, 0.99, 1),
(25, 26, 0.99, 1), (25, 28, 0.99, 1);

-- Playlists
INSERT INTO playlist (name) VALUES
('Music'), ('Movies'), ('TV Shows'), ('90''s Music'), ('Classical'),
('Heavy Metal Classic'), ('Grunge');

INSERT INTO playlist_track (playlist_id, track_id) VALUES
(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8), (1, 9), (1, 10),
(1, 11), (1, 12), (1, 13), (1, 14), (1, 15), (1, 16), (1, 17), (1, 18), (1, 19), (1, 20),
(4, 20), (4, 21), (4, 22), (4, 23), (4, 24), (4, 25), (4, 26),
(6, 11), (6, 12), (6, 27), (6, 28),
(7, 18), (7, 19), (7, 20), (7, 21), (7, 22), (7, 23), (7, 25), (7, 26);

-- Create useful indexes
CREATE INDEX idx_track_album ON track(album_id);
CREATE INDEX idx_track_genre ON track(genre_id);
CREATE INDEX idx_album_artist ON album(artist_id);
CREATE INDEX idx_invoice_customer ON invoice(customer_id);
CREATE INDEX idx_invoice_date ON invoice(invoice_date);
CREATE INDEX idx_invoice_line_invoice ON invoice_line(invoice_id);
CREATE INDEX idx_invoice_line_track ON invoice_line(track_id);
CREATE INDEX idx_customer_support_rep ON customer(support_rep_id);
