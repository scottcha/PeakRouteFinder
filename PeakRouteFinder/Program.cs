using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Diagnostics;
using System.Device.Location;
namespace PeakRouteFinder
{
    public class Program
    {
        public List<List<double>> distanceLookup { get; set;}
        static void Main(string[] args)
        {
            var fileName = args[0];

            string[] lines = System.IO.File.ReadAllLines(fileName);
            bool firstLine = true;
            System.Collections.Generic.
            List<Peak> peaks = new List<Peak>();
            foreach(string line in lines)
            {
                if(firstLine)
                {
                    firstLine = false;
                    continue;
                }
                string[] lineComponents = line.Split(',');
                Debug.Assert(lineComponents.Length == 3);
                peaks.Add(new Peak() { name = lineComponents[2], lat = float.Parse(lineComponents[0]), lon = float.Parse(lineComponents[1]) });
            }

            var p = new Program();
            p.InitializeDistanceLookup(peaks);
            p.PrintPeakDistances(peaks);
        }

        public void InitializeDistanceLookup(List<Peak> peaks)
        {
            distanceLookup = new List<List<double>>();
            for(int p1 = 0; p1 < peaks.Count; p1++)
            {
                distanceLookup.Add(new List<double>());
                for(int p2 = 0; p2 < peaks.Count; p2++)
                {
                    distanceLookup[p1].Add(CalculateDistance(peaks[p1], peaks[p2]));
                }
            }
        }

        public static double CalculateDistance(Peak peak1, Peak peak2)
        {
        http://stackoverflow.com/questions/6366408/calculating-distance-between-two-latitude-and-longitude-geocoordinates 
            return MetersToMiles(peak1.geoCoordinate.GetDistanceTo(peak2.geoCoordinate));
        }
        
        public static double MetersToMiles(double distance)
        {
            const double metersToMilesConstant = 0.000621371192;
            return distance * metersToMilesConstant;
        }
        public void PrintPeakDistances(List<Peak> peaks)
        {
            using(System.IO.StreamWriter file = new System.IO.StreamWriter("PeakDistances.csv"))
            {
                //first column has blank header
                file.Write(", ");
                foreach(Peak p in peaks)
                {
                    //write the column headers
                    file.Write(p.name + ", ");
                }
                file.Write("\n");

                //now write the row header then row values
                for(int p1 = 0; p1 < peaks.Count; p1++)
                {
                    //first the row name
                    file.Write(peaks[p1].name + ", ");
                    for(int p2 = 0; p2 < peaks.Count; p2++)
                    {
                        //now the row values
                        if (p2 != peaks.Count - 1)
                        {
                            file.Write(distanceLookup[p1][p2] + ", ");
                        }
                        else
                        {
                            file.Write(distanceLookup[p1][p2] + "\n");
                        }
                    }
                }
                file.Close();
            }
        }
    }
}
