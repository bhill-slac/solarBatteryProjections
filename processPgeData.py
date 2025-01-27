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
        self.NewSolar  = 0      # kWh
        self.OldSolar  = 0      # kWh
        self.Export    = 0      # kWh
        self.TimeOfDay = datetime.now()
    def __init__( self, time, grid=0, battery=0, charging=0, newSolar=0, oldSolar=0, export=0 ):
        self.Grid      = grid      # kWh
        self.Battery   = battery   # kWh
        self.Charging  = charging  # kWh
        self.NewSolar  = newSolar  # kWh
        self.OldSolar  = oldSolar  # kWh
        self.Export    = export    # kWh
        self.TimeOfDay = time
    def __str__( self ):
        #return f"{self.TimeOfDay}: Grid={self.Grid:>6.2f}, Charging={self.Charging:>6.2f}, Battery={self.Battery:>6.2f}, Export={self.Export:>6.2f}" 
        return f"{self.TimeOfDay}: Grid={self.Grid:>6.2f}, Charging={self.Charging:>6.2f}, Battery={self.Battery:>6.2f}, Export={self.Export:>6.2f}, NewSolar={self.NewSolar:>6.2f}, OldSolar={self.OldSolar:>6.2f}" 

    def ApplyBatteryToGrid( self ):
        if self.Grid > 0 and self.Battery > 0:
            if self.Battery >= self.Grid:
                self.Battery -= self.Grid
                self.Grid = 0
            else:
                self.Grid -= self.Battery
                self.Battery = 0
        if self.Grid < 0:
            print( "Error: {self}" )
 
    def ApplyNewSolarToBattery( self, options ):
        if self.NewSolar <= 0:
            return
        if self.Battery >= options.MaxBattery:
            return
        availCharge = self.NewSolar * options.Efficiency / 100
        newCharge = min( availCharge, options.MaxBattery - self.Battery )
        self.Battery = min( self.Battery + newCharge, options.MaxBattery )
        self.Charging += newCharge
        self.NewSolar = max( 0, self.NewSolar - newCharge / (options.Efficiency/100) )
 
    def ApplyOldSolarToBattery( self, options ):
        if self.OldSolar <= 0:
            return
        if self.Battery >= options.MaxBattery:
            return
        availCharge = self.OldSolar * options.Efficiency / 100
        newCharge = min( availCharge, options.MaxBattery - self.Battery )
        self.Battery = min( self.Battery + newCharge, options.MaxBattery )
        self.Charging += newCharge
        self.OldSolar = max( 0, self.OldSolar - newCharge / (options.Efficiency/100) )

    def ApplyOldSolarToGrid( self ):
        if self.Grid > 0 and self.OldSolar > 0:
            if self.OldSolar >= self.Grid:
                self.OldSolar -= self.Grid
                self.Grid = 0
            else:
                self.Grid -= self.OldSolar
                self.OldSolar = 0
        if self.Grid < 0:
            print( "Error: {self}" )
 
    def ApplyNewSolarToGrid( self ):
        if self.Grid > 0 and self.NewSolar > 0:
            if self.NewSolar >= self.Grid:
                self.NewSolar -= self.Grid
                self.Grid = 0
            else:
                self.Grid -= self.NewSolar
                self.NewSolar = 0
        if self.Grid < 0:
            print( "Error: {self}" )
 
    def ExportNewSolarToGrid( self ):
        if self.NewSolar > 0:
            self.Export += self.NewSolar
            self.NewSolar = 0

    def ExportOldSolarToGrid( self ):
        if self.OldSolar > 0:
            self.Export += self.OldSolar
            self.OldSolar = 0
 
#   Options for home solar projections
#   opt1 = Option( 'E-ELEC', '1.0', 13.5, 5600 )
class   Option:
    def __init__( self, ratePlan, nem, maxBattery, newSolarProd, efficiency=95 ):
        self.RatePlan     = ratePlan      # 'E-ELEC' or 'E-TOU-C' or 'E-TOU-D'
        self.NEM          = nem           # '1.0' or '3.0'
        self.MaxBattery   = maxBattery    # kWh
        self.Efficiency   = efficiency    # %
        self.NewSolarProd = newSolarProd  # Yearly kWh
        self.Proj         = []
    def __str__( self ):
        return f"RatePlan={self.RatePlan:>7}, NEM={self.NEM}, MaxBattery={self.MaxBattery}, Efficiency={self.Efficiency}, NewSolarProd={self.NewSolarProd}" 

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

def DebugThisDay( timeOfDay, year, month, day ):
    if timeOfDay.year == year and timeOfDay.month == month and timeOfDay.day == day:
        return True
    return False

class   HomeSolar:
    def __init__( self ):
        self.hourlyData = []
        self.options = []

    def AddOption( self, option ):
        self.options.append( option )
        print( f'Adding option: {option}' )
        battery = option.MaxBattery / 2
        option.Proj.append( HourlyProj( time=self.hourlyData[0].TimeOfDay, battery=battery ) )
        for data in self.hourlyData:
            oldSolar = -data.SolarProd
            if oldSolar < 0.02: oldSolar = 0 # Clean up output by eliminating trivial solar kWh due to CT accuracy limits
            newSolar = oldSolar * (option.NewSolarProd / oldSolarYearlyProd)
            verbose = False # DebugPeakVsOffPeakTimes(data.TimeOfDay)
            verbose = DebugThisDay( data.TimeOfDay, data.TimeOfDay.year, 8, 1 )

            newHour = HourlyProj( time=data.TimeOfDay, grid=data.Usage, battery=battery, oldSolar=oldSolar, newSolar=newSolar )
            #if verbose: print( newHour )
            if isPeakTime( data.TimeOfDay, option.RatePlan ):
                #
                # Handle Peak periods
                #
                # Use NewSolar first
                newHour.ApplyNewSolarToGrid( )
                if option.NEM == '1.0':
                    # Battery then OldSolar
                    newHour.ApplyBatteryToGrid( )
                    newHour.ApplyOldSolarToGrid( )
                else:
                    # OldSolar then Battery
                    newHour.ApplyBatteryToGrid( )
                    newHour.ApplyOldSolarToGrid( )
            elif isPartialPeakTime( data.TimeOfDay, option.RatePlan ):
                #
                # Handle PartialPeak periods
                #
                # Rough estimate of upcoming 5 hours of peak usage
                estPeakUsage = data.Usage * 5.5
                newHour.ApplyNewSolarToGrid( )
                if option.NEM == '1.0':
                    # Only use battery for 3-4pm partial peak if we can cover peak usage too
                    if data.TimeOfDay.hour == 3 and newHour.Battery > data.Usage + estPeakUsage:
                        newHour.ApplyBatteryToGrid( )
                    newHour.ApplyOldSolarToGrid( )
                else:
                    newHour.ApplyOldSolarToGrid( )
                    # Only use battery if we can cover peak usage too
                    if newHour.Battery > data.Usage + estPeakUsage:
                        newHour.ApplyBatteryToGrid( )
            elif isOffPeakTime( data.TimeOfDay, option.RatePlan ):
                #
                # Handle OffPeak periods
                #
                newHour.ApplyNewSolarToGrid( )
                newHour.ApplyOldSolarToGrid( )
                
                newHour.ApplyNewSolarToBattery( option )
                if option.NewSolarProd == 0 or option.NEM == '3.0':
                    # If we add new solar under NEM 1.0 via non-export, 
                    # we can only charge the battery from NewSolar
                    newHour.ApplyOldSolarToBattery( option )

                # Apply remaining battery to grid
                newHour.ApplyBatteryToGrid( )

            # Apply remaining peak or partial peak NewSolar to battery
            newHour.ApplyNewSolarToBattery( option )

            # Export excess solar to grid
            if option.NEM == '3.0':
                newHour.ExportNewSolarToGrid( )
            newHour.ExportOldSolarToGrid( )
            newHour.TimeOfDay += timedelta( minutes=59, seconds=59 )

            # Hold remaining battery for next hour
            battery = newHour.Battery
            if verbose:
                print( newHour )

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
            usage = max( 0, usage + solarProd )
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
        sys.stderr.write('I/O Error %s: Could not open "%s"\n' % (pgeDataFile, str(message)))
        raise
    except:
        print(repr(sys.exception()))
        raise

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
        sys.stderr.write('I/O Error %s: Could not open "%s"\n' % (vueDataFile, str(message)))
        raise
    except:
        print(repr(sys.exception()))
        raise

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

    #myHomeSolar.AddOption( Option( 'E-TOU-D', '1.0', 0, 0 ) )
    #myHomeSolar.AddOption( Option( 'E-TOU-C', '1.0', 0, 0 ) )
    myHomeSolar.AddOption( Option( 'E-ELEC', '1.0', 13.5, 0 ) )
    #myHomeSolar.AddOption( Option( 'E-ELEC', '1.0', 13.5, 5600 ) )
    myHomeSolar.AddOption( Option( 'E-ELEC', '1.0', 13.5, 11214 ) )
    #myHomeSolar.AddOption( Option( 'E-ELEC', '3.0', 13.5, 5600 ) )
    return 0

if __name__ == '__main__':
    status = main()
    sys.exit(status)

