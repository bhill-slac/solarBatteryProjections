#!python
import csv
import sys
import argparse
import datetime
import dateutil
from datetime import timedelta

# Note: Look for PGE usage on day I shutoff our solar for the day.
# Should be around Dec 23, 2009
# Also look at impact after I washed solar panels 1/17/09

oldSolarYearlyProd = 5732

vueDateLabel  = 'Time Bucket (America/Los_Angeles)'
vueSolarLabel = 'Main panel-Solar/Generation-Solar inverter (kWhs)'
pgeData = {}
vueData = {}

# N_HOURS_MAX = 366 * 24

def isPeakTime( timeOfDay, ratePlan ):
    if ratePlan == 'E-TOU-D':
        # E-TOU-D Weekdays 5-8pm Peak, otherwise OffPeak
        if timeOfDay.weekday() >= 5:
            return False
        if timeOfDay.hour < 17 or timeOfDay.hour >= 20:
            return False
        return True
    # Other rate plans have peak hours 4pm to 9pm
    if timeOfDay.hour < 16 or timeOfDay.hour >= 21:
        return False
    return True

def isPartialPeakTime( timeOfDay, ratePlan ):
    if ratePlan == 'E-TOU-D':
        # E-TOU-D Weekdays 5-8pm Peak, otherwise OffPeak, No Partial Peak
        return False
    if ratePlan == 'E-TOU-C':
        # E-TOU-C Every day 4-9pm Peak, otherwise OffPeak, No Partial Peak
        return False
    if ratePlan == 'E-ELEC':
        # E-ELEC Partial Peak Every day 3pm-4pm and 9pm to midnight
        if timeOfDay.hour == 15 or timeOfDay.hour >= 21:
            return True
        return False
    return False

def isOffPeakTime( timeOfDay, ratePlan ):
    if ratePlan == 'E-TOU-D':
        # E-TOU-D Weekdays 5-8pm Peak, otherwise OffPeak, No Partial Peak
        return not isPeakTime( timeOfDay, 'E-TOU-D' )
    if ratePlan == 'E-TOU-C':
        # E-TOU-C Every day 4-9pm Peak, otherwise OffPeak, No Partial Peak
        return not isPeakTime( timeOfDay, 'E-TOU-C' )
    if ratePlan == 'E-ELEC':
        # E-ELEC Off Peak Every day midnight to 3pm
        if timeOfDay.hour < 15:
            return True
        return False
    return False

class   HourlyData:
    def __init__( self ):
        self.Usage     = 0
        self.SolarProd = 0
        self.TimeOfDay = datetime.now()
    def __init__( self, usage, solarProd, timeOfDay ):
        self.Usage     = usage
        self.SolarProd = solarProd
        self.TimeOfDay = timeOfDay

def isSummerPeakTime( timeOfDay, ratePlan ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return isPeakTime( timeOfDay, ratePlan )
    return False

def isWinterPeakTime( timeOfDay, ratePlan ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return isPeakTime( timeOfDay, ratePlan )
    return False

def isSummerPartialPeakTime( timeOfDay, ratePlan ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return isPartialPeakTime( timeOfDay, ratePlan )
    return False

def isWinterPartialPeakTime( timeOfDay, ratePlan ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return isPartialPeakTime( timeOfDay, ratePlan )
    return False

def isSummerOffPeakTime( timeOfDay, ratePlan ):
    # Summer is June through end of Sept
    if timeOfDay.month >= 6 and timeOfDay.month <= 9:
        return isOffPeakTime( timeOfDay, ratePlan )
    return False

def isWinterOffPeakTime( timeOfDay, ratePlan ):
    # Winter is Oct through end of May
    if timeOfDay.month <= 5 or timeOfDay.month >= 10:
        return isOffPeakTime( timeOfDay, ratePlan )
    return False

class   HourlyProj:
    def __init__( self ):
        self.Grid      = 0      # kWh
        self.Battery   = 0      # kWh
        self.Charging  = 0      # kWh
        self.Solar     = 0      # kWh
        self.Export    = 0      # kWh
        self.TimeOfDay = datetime.now()
    def __init__( self, grid, battery, charge, solar, export, time ):
        self.Grid      = grid      # kWh
        self.Battery   = battery   # kWh
        self.Charging  = charge    # kWh
        self.Solar     = solar     # kWh
        self.Export    = export    # kWh
        self.TimeOfDay = time

#   Options for home solar projections
#   opt1 = Option( 'E-ELEC', '1.0', 13.5, 5600 )
class   Option:
    def __init__( self, ratePlan, nem, maxBattery, newSolar ):
        self.RatePlan   = ratePlan    # 'E-ELEC' or 'E-TOU-C' or 'E-TOU-D'
        self.NEM        = nem         # '1.0' or '3.0'
        self.MaxBattery = maxBattery  # kWh
        self.NewSolar   = newSolar    # Yearly kWh
        self.Proj       = []

def DebugPeakVsOffPeakTimes( timeOfDay ):
    debugWinter2Summer = datetime.datetime( year=timeOfDay.year, month=6, day = 1 )
    debugSummer2Winter = datetime.datetime( year=timeOfDay.year, month=10, day = 1 )
    debugInterval = timedelta(days=1) 
    if (   abs(timeOfDay - debugSummer2Winter) <= debugInterval
        or abs(timeOfDay - debugWinter2Summer) <= debugInterval ):
        dataHour = timeOfDay.hour
        if dataHour >= 14:
            return True
    return False

class   HomeSolar:
    def __init__( self ):
        self.hourlyData = []
        self.options = []

    def AddOption( self, option ):
        self.options.append( option )
        battery = option.MaxBattery / 2
        option.Proj.append( HourlyProj( 0, battery, 0, 0, 0, self.hourlyData[0].TimeOfDay ) )
        for data in self.hourlyData:
            usage = data.Usage
            oldSolar = data.SolarProd
            newSolar = oldSolar * (option.NewSolar / oldSolarYearlyProd)
            verbose = DebugPeakVsOffPeakTimes(data.TimeOfDay)

            if isPeakTime( data.TimeOfDay, option.RatePlan ):
                # Handle Peak periods
                if verbose and isSummerPeakTime( data.TimeOfDay, option.RatePlan ):
                    print( "%s: %s is Summer Peak" % ( option.RatePlan, data.TimeOfDay ) )
                if verbose and isWinterPeakTime( data.TimeOfDay, option.RatePlan ):
                    print( "%s: %s is Winter Peak" % ( option.RatePlan, data.TimeOfDay ) )
            elif isPartialPeakTime( data.TimeOfDay, option.RatePlan ):
                if verbose and isSummerPartialPeakTime( data.TimeOfDay, option.RatePlan ):
                    print( "%s: %s is Summer PartialPeak" % ( option.RatePlan, data.TimeOfDay ) )
                if verbose and isWinterPartialPeakTime( data.TimeOfDay, option.RatePlan ):
                    print( "%s: %s is Winter PartialPeak" % ( option.RatePlan, data.TimeOfDay ) )
                # Handle PartialPeak periods
            elif isOffPeakTime( data.TimeOfDay, option.RatePlan ):
                if verbose and isSummerOffPeakTime( data.TimeOfDay, option.RatePlan ):
                    print( "%s: %s is Summer OffPeak" % ( option.RatePlan, data.TimeOfDay ) )
                if verbose and isWinterOffPeakTime( data.TimeOfDay, option.RatePlan ):
                    print( "%s: %s is Winter OffPeak" % ( option.RatePlan, data.TimeOfDay ) )
                # Handle OffPeak periods

    def ProcessDataFiles( self, pgeData, vueData, verbose = False ):
        # Note: Both data files have 23 entries for start of DST, 3/10/24
        # pgeData has 24 entries for DST, 11/3/24
        # vueData has 25 entries, but we add 1 min to the duplicate 1:00 am as
        # 11/3/24 actually lasts for 25 hours.
        # vueData also includes an extra entry for midnight on the day after the last export day
        # i.e.  Exporting 1/1/24 to 12/31/24 includes an entry for 1/1/25 00:00
        usage = 0
        extraHour  = max(vueData.keys())
        for hourTime, solarProd in vueData.items():
            if hourTime in pgeData:
                usage = pgeData[hourTime]
            # solarProd is negative and needs to be added
            # to PGE usage to reflect actual usage w/o solar
            usage = usage + solarProd
            if hourTime < extraHour:
                self.hourlyData.append( HourlyData( usage, solarProd, hourTime ) )
        if verbose:
            print( 'Processed %u hourly usage and solarProd values.' % len(self.hourlyData) )
            print( 'From %s to %s' % ( self.hourlyData[0].TimeOfDay.strftime('%m/%d/%Y, %H:%M'),
                                       self.hourlyData[-1].TimeOfDay.strftime('%m/%d/%Y, %H:%M') ) )

def readPgeData( pgeDataFile, verbose=False ):
    pgeData = {}
    try:
        in_file = open( pgeDataFile, 'r' )
        blankLine = in_file.readline()
        nameLine = in_file.readline()
        if nameLine.split(',')[0] != 'Name':
            print( '2nd line in PGE Data File should be Name of acct owner, not\n%s\n' % nameLine )
        if verbose:
            print( nameLine )
        addrLine = in_file.readline()
        if addrLine.split(',')[0] != 'Address':
            print( '3rd line in PGE Data File should be Address of acct owner, not\n%s\n' % addrLine )
        acctLine = in_file.readline()
        if acctLine.split(',')[0] != 'Account Number':
            print( '4th line in PGE Data File should be Account Number, not\n%s\n' % acctLine )
        svcLine  = in_file.readline()
        if svcLine.split(',')[0] != 'Service':
            print( '5th line in PGE Data File should be Service, not\n%s\n' % svcLine )
        blankLine = in_file.readline()

    except IOError as v:
        try:
            (code, message) = v
        except:
            code = 0
            message = v
        print(repr(sys.exception()))
        sys.stderr.write('I/O Error %s: Could not open "%s": %s\n' % (pgeDataFile, str(message)))
        return pgeData
    except:
        print(repr(sys.exception()))
        return pgeData

    csv_reader = csv.DictReader(in_file)

    numRows = 0
    rowTime = datetime.datetime.now()
    for row in csv_reader:
        numRows = numRows+1
        rowDate = dateutil.parser.parse( row['DATE'] )
        rowStart = dateutil.parser.parse( row['START TIME'] )
        rowEnd   = dateutil.parser.parse( row['END TIME'] )
        if 'USAGE (kWh)' in csv_reader.fieldnames:
            usage = float( row['USAGE (kWh)'])
        else:
            usage = float( row['IMPORT (kWh)'])
            usage -= float( row['EXPORT (kWh)'])

        rowTime = rowDate + datetime.timedelta(hours=rowStart.hour, minutes=rowStart.minute)
        if rowTime in pgeData:
            rowTime = rowTime + datetime.timedelta(minutes=1)
        pgeData[rowTime] = usage
        if verbose and len(pgeData) <= 1:
            print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), usage ) )
    if verbose:
        print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), usage ) )

    return pgeData

def readVueData( vueDataFile, verbose=False ):
    vueData = {}
    try:
        in_file = open( vueDataFile, 'r' )

    except IOError as v:
        try:
            (code, message) = v
        except:
            code = 0
            message = v
        print(repr(sys.exception()))
        sys.stderr.write('I/O Error %s: Could not open "%s": %s\n' % (vueDataFile, str(message)))
        return vueData
    except:
        print(repr(sys.exception()))
        return vueData

    csv_reader = csv.DictReader(in_file)
    numRows = 0
    rowTime = datetime.datetime.now()
    for row in csv_reader:
        numRows = numRows+1
        rowTime = dateutil.parser.parse( row[vueDateLabel] )
        if vueSolarLabel in csv_reader.fieldnames:
            solarOutput = float( row[vueSolarLabel])
        if rowTime in vueData:
            rowTime = rowTime + datetime.timedelta(minutes=1)
        vueData[rowTime] = solarOutput
        if verbose and len(vueData) <= 1:
            print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), solarOutput ) )
    if verbose:
        print( "%s: %.2f" % ( rowTime.strftime('%m/%d/%Y, %H:%M'), solarOutput ) )
    return vueData

def process_options(argv):
    if argv is None:
       argv = sys.argv[1:]
    desc = 'processPgeData reads PGE data files and analyses them.'
    parser = argparse.ArgumentParser( description = desc )
    parser.add_argument( '-f', '--pgeDataFiles', dest='pgeDataFiles', action='append', \
            help='Read PGE Data File -f pgeDataFile1.csv [-f pgeDataFile2.csv]' )
    parser.add_argument( '-e', '--vueDataFiles', dest='vueDataFiles', action='append', \
            help='Read Emporia Vue data file.' )
    parser.add_argument( '-v', '--verbose', action='store_true', help='show verbose diags' )
    options = parser.parse_args()
    return options

def main(argv=None):
    options = process_options(argv)

    if options.pgeDataFiles:
        for pgeDataFile in options.pgeDataFiles:
            newData = readPgeData( pgeDataFile, verbose=options.verbose )
            if options.verbose:
                print( 'Read  "%u" PGE Data Points' % len(newData) )
            pgeData.update(newData)

    if options.verbose:
        print( 'Total "%u" PGE Data Points' % len(pgeData) )
        print( 'From %s to %s' % ( min(pgeData.keys()).strftime('%m/%d/%Y, %H:%M'),
                                   max(pgeData.keys()).strftime('%m/%d/%Y, %H:%M') ) )

    if options.vueDataFiles:
        for vueDataFile in options.vueDataFiles:
            newData = readVueData( vueDataFile, verbose=options.verbose )
            if options.verbose:
                print( 'Read  "%u" VUE Data Points' % len(newData) )
            vueData.update(newData)

    if options.verbose:
        print( 'Total "%u" VUE Data Points' % len(vueData) )
        print( 'From %s to %s' % ( min(vueData.keys()).strftime('%m/%d/%Y, %H:%M'),
                                   max(vueData.keys()).strftime('%m/%d/%Y, %H:%M') ) )

    myHomeSolar = HomeSolar()
    myHomeSolar.ProcessDataFiles( pgeData, vueData, options.verbose )

    myHomeSolar.AddOption( Option( 'E-TOU-D', '1.0', 0, 0 ) )
    myHomeSolar.AddOption( Option( 'E-TOU-C', '1.0', 0, 0 ) )
    myHomeSolar.AddOption( Option( 'E-ELEC', '1.0', 13.5, 0 ) )
    # myHomeSolar.AddOption( Option( 'E-ELEC', '1.0', 13.5, 5600 ) )
    # myHomeSolar.AddOption( Option( 'E-ELEC', '1.0', 13.5, 11214 ) )
    # myHomeSolar.AddOption( Option( 'E-ELEC', '3.0', 13.5, 5600 ) )
    return None

if __name__ == '__main__':
    status = main()
    sys.exit(status)

