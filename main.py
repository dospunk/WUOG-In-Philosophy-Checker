import billboard
import sqlite3
import sys
from typing import TypeVar, Dict, NamedTuple, Union
if sys.platform == "win32":
	import msvcrt
else:
	import getch
from datetime import timedelta, date

#https://stackoverflow.com/a/16726460/6645696 might be a good idea to separate searching and updating, since this would be
#undoubtedly faster

# TYPES
class FoundInfo(NamedTuple):
	date: str
	artist: str
	position: int

#CONSTANTS
ODD_DATES = { #for dates that don't follow the normal pattern of always being on a Saturday
  "1976-07-03": date(1976, 7, 4)
}
TODAY = date.today()
TWENTY_YEARS_AGO = date(TODAY.year-20, TODAY.month, TODAY.day)
BILLBOARD_200_EARLIEST = date(1963, 8, 17)
ARTIST_SEPARATOR = "`~"

def flush_stdin():
	'''multi-platform way to flush stdin'''
	if sys.platform == "win32":
		while msvcrt.kbhit():
			msvcrt.getch()
	else:
		sys.stdin.flush()

def get_char() -> str:
	'''multi-platform getch that always returns a string'''
	if sys.platform == "win32":
		return msvcrt.getch().decode("ASCII")
	else:
		return getch.getch()

def directly_follows(a: str, b: str, src: str) -> bool:
	'''Finds if a directly follows b in src'''
	return b+a in src

VT = TypeVar('VT')
KT = TypeVar('KT')
def key_from_value(d: Dict[KT, VT], val: VT) -> KT:
	'''Gets the key that corresponds to val in d'''
	return list(d.keys())[list(d.values()).index(val)]

def chart_name_to_table_name(chart_name: str) -> str:
	if chart_name == "hot-100":
		return "hot100"
	elif chart_name == "billboard-200":
		return "bb200"
	else:
		return ""

def fetch_and_insert_date(datestr: str, chart_name: str, dbconn: sqlite3.Connection) -> str:
	'''fetches the chart chart_name at date datestr and inserts the relevant information into the database'''
	table_name = chart_name_to_table_name(chart_name)
	dbcurs = dbconn.cursor()
	print(f"database does not contain entry for {datestr}, fetching now")
	#fetch data from billboard
	chart = billboard.ChartData(chart_name, datestr)
	#insert that date into the database
	entries = chart[0:] if chart_name == "hot-100" else chart[0:20]
	artists_str = ARTIST_SEPARATOR.join([entry.artist for entry in entries]).lower()
	data = (chart.date, artists_str)
	dbcurs.execute(f"INSERT INTO {table_name} VALUES (?,?)", data)
	dbconn.commit()
	return artists_str

def find_in_table(
	artist: str,
	dbconn: sqlite3.Connection,
	start_date: date,
	stop_date: date,
	chart_name: str) -> Union[FoundInfo, None]:
	#get the table name based on the chart name
	table_name = chart_name_to_table_name(chart_name)
	#get the most recent chart and use its date as the starting point
	start_chart = billboard.ChartData(chart_name, start_date.isoformat())
	curr_week = date.fromisoformat(str(start_chart.date))
	#get the database cursor
	dbcurs = dbconn.cursor()
	while curr_week > stop_date:
		#check if the current date is known to not match the standard Billboard chart dates (not on a saturday)
		curr_is_odd_date = False
		if curr_week.isoformat() in ODD_DATES:
			#if so, get the proper date for this chart
			curr_is_odd_date = True
			curr_week = ODD_DATES[curr_week.isoformat()]
		#get the artists in the database for that date
		dbcurs.execute(f"SELECT artists FROM {table_name} WHERE date = ?", (curr_week.isoformat(),))
		#fetch the response from the database and declare a variable to store the artists string in
		res = dbcurs.fetchone()
		res_str: str
		if res == None: #if date is not in the table, fetch it and insert the data into the table
			res_str = fetch_and_insert_date(curr_week.isoformat(), chart_name, dbconn)
		else: #otherwise, set res_str to the artists
			res_str = res[0]
		#check if the artist shows up in the response string anywhere
		if artist in res_str and not directly_follows(artist, " featuring ", res_str):
			#if it does, split the string
			artists_list = res_str.split(ARTIST_SEPARATOR)
			#and then find which entry the searched-for artist appears in
			for i in range(len(artists_list)):
				a = artists_list[i]
				if artist in a:
					return FoundInfo(curr_week.isoformat(), a, i+1)
		#if the current date is an odd date, restore the original date to get back to the normal pattern
		if curr_is_odd_date:
			curr_week = date.fromisoformat(key_from_value(ODD_DATES, curr_week))
		#check the next date
		curr_week = curr_week - timedelta(weeks=1)
	#if the artist is not found, return None
	return None

def find_in_hot100(artist: str, start_date: date, dbconn: sqlite3.Connection) -> Union[FoundInfo, None]:
	return find_in_table(artist, dbconn, start_date, TWENTY_YEARS_AGO, "hot-100")

def find_in_bb200(artist: str, start_date: date, dbconn: sqlite3.Connection) -> Union[FoundInfo, None]:
	return find_in_table(artist, dbconn, start_date, BILLBOARD_200_EARLIEST, "billboard-200")

def init_db() -> sqlite3.Connection:
	conn = sqlite3.connect("billboard.db")
	curs = conn.cursor()
	#create tables if they dont exist
	curs.execute("create table if not exists hot100 (date TEXT NOT NULL PRIMARY KEY, artists TEXT NOT NULL)")
	curs.execute("create table if not exists bb200 (date TEXT NOT NULL PRIMARY KEY, artists TEXT NOT NULL)")
	conn.commit()
	#delete entries in hot100 that are older than  20 years ago
	curs.execute("DELETE FROM hot100 WHERE date < date('now','-20 years')")
	#delete any empty entries because apparently that happens
	curs.execute("DELETE FROM hot100 WHERE artists=''")
	curs.execute("DELETE FROM bb200 WHERE artists=''")
	conn.commit()
	return conn

def continue_or_quit():
	'''Prints a prompt and allows the user to either continue with the current activity or quit the program'''
	print("Press [c] to continue searching, or [q] to quit")
	flush_stdin()
	key = get_char()
	while key != 'c':
		if key == 'q':
			sys.exit()
		else:
			key = get_char()
	
def output_found_artist(query: str, chart: str, data: FoundInfo):
	chart_name = chart.replace("-", " ").capitalize()
	print(f"{query} found in {chart_name} on {data.date} at position {data.position} in the listing \"{data.artist}\"")
	print(f"( https://www.billboard.com/charts/{chart}/{data.date} )")

def main():
	conn = init_db()
	while True:
		query = input("artist name: ")
		query = query.strip()
		query_lowered = query.lower()
		print("Searching in Hot 100")
		hot100_found_data = find_in_hot100(query_lowered, TODAY, conn)
		while hot100_found_data:
			output_found_artist(query, "hot-100", hot100_found_data)
			continue_or_quit()
			print("Continuing...")
			next_date = date.fromisoformat(hot100_found_data.date) - timedelta(weeks=1)
			hot100_found_data = find_in_hot100(query_lowered, next_date, conn)
		print("Searching in Billboard 200")
		bb200_found_data = find_in_bb200(query_lowered, TODAY, conn)
		while bb200_found_data:
			output_found_artist(query, "billboard-200", bb200_found_data)
			continue_or_quit()
			print("Continuing...")
			next_date = date.fromisoformat(bb200_found_data.date) - timedelta(weeks=1)
			bb200_found_data = find_in_bb200(query_lowered, next_date, conn)
		print(f"{query} not found, you're good to go!")
		print("If you would like to search for another artist, continue")
		continue_or_quit()


if __name__ == "__main__":
	main()